"""Approved recent-rain framing preserves each real reader and every evidence gap."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import scout_cwa_environment_tool as cwa
import scout_gee_environment_tool as gee
from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_full_workflow import run_scout_ai_full_workflow
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from weather_workflow_fixtures import REFERENCE_TIME, weather_tool_calls, write_missing_weather_project

WEATHER = WEATHER_WINDOW_TOOL_ID
CWA = cwa.CWA_ENVIRONMENT_TOOL_ID
GEE = gee.GEE_ENVIRONMENT_TOOL_ID
RAIN = "前 24 小時明顯降雨，溪水和崩塌風險是否升高？今天還能走嗎？"
RULE = "query_reported_recent_rain_missing_support.v1"
FIXTURES = Path(__file__).parent / "fixtures"
HISTORICAL = FIXTURES / "pretrip/projects/chilai_nanhua_day1"
COMMON = "outputs/environment/environment_evidence_package.json"
OBS = "outputs/environment/cwa/observations.geojson"
QPF = "outputs/environment/cwa/qpf_corridor_summary.json"
WARNING = "outputs/environment/cwa/warnings.geojson"
SMAP = "outputs/environment/gee/smap_l4_corridor_summary.json"
GPM = "outputs/environment/gee/gpm_imerg_corridor_summary.json"
TIMESERIES = "outputs/environment/gee/smap_l4_timeseries.json"
PARTIAL = {COMMON, OBS, TIMESERIES}


@pytest.fixture(autouse=True)
def preserve_actual_payloads(monkeypatch, weather_tool_calls):
    """Observe actual native objects and the complete collected evidence boundary."""
    import scout_ai_answer_synthesis as synthesis
    import scout_ai_evidence_collection as collection

    execute = collection.execute_scout_ai_tool
    synthesize = synthesis.synthesize_scout_ai_answer_from_evidence
    raw_objects = []

    def observe_execute(request):
        result = execute(request)
        raw_objects.append((result, deepcopy(result.model_dump(mode="json"))))
        return result

    def observe_synthesis(evidence):
        before = deepcopy(evidence.model_dump(mode="json"))
        result = synthesize(evidence)
        assert evidence.model_dump(mode="json") == before
        assert result.evidence_collection == before
        return result

    monkeypatch.setattr(collection, "execute_scout_ai_tool", observe_execute)
    monkeypatch.setattr(synthesis, "synthesize_scout_ai_answer_from_evidence", observe_synthesis)
    yield
    for actual, before in raw_objects:
        assert actual.model_dump(mode="json") == before


def _write(root, name, payload):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False))


def _project(tmp_path, scenario):
    root = write_missing_weather_project(tmp_path, HISTORICAL)
    if scenario == "missing":
        return root
    definitions = json.loads((FIXTURES / "weather_workflow/prepared-environment-artifacts.json").read_text())
    original = definitions["artifacts"]
    background = deepcopy(original)
    background.update(deepcopy(definitions["cwa_profiles"]["background"]))
    background[SMAP]["metrics"]["sm_surface_wetness"]["latest"] = 0.2
    background[GPM]["metrics"]["rain_72h_mm"]["latest"] = 20.0
    if scenario in {"partial", "cwa-stale", "cwa-future", "gee-stale", "gee-future"}:
        names = set(PARTIAL)
    elif scenario.startswith("pressure-"):
        extra = {"pressure-cwa-warning": WARNING, "pressure-cwa-qpf": QPF,
                 "pressure-gee-wetness": SMAP, "pressure-gee-rain": GPM}[scenario]
        names = PARTIAL | {extra}
        background[extra] = deepcopy(original[extra])
    elif scenario == "missing-cwa":
        names = {name for name in background if "/cwa/" not in name}
    elif scenario == "missing-gee":
        names = {name for name in background if "/gee/" not in name}
    else:
        assert scenario == "complete"
        names = set(background)
    if scenario.endswith(("-stale", "-future")):
        artifact = OBS if scenario.startswith("cwa-") else TIMESERIES
        background[artifact]["request_timestamp"] = (
            "2020-01-01T00:00:00Z" if scenario.endswith("-stale") else "2030-01-01T00:00:00Z"
        )
    for name in sorted(names):
        _write(root, name, background[name])
    return root


def _hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _run(root, entrypoint, calls, query=RAIN):
    before = _hashes(root)
    result = entrypoint(query, project_root=root, project_id="chilai_nanhua_day1",
                        reference_time=REFERENCE_TIME, limit=5).model_dump(mode="json")
    assert _hashes(root) == before
    records = result["evidence_collection"]["evidence_records"]
    ids = [record["tool_id"] for record in records]
    assert len(ids) == len(set(ids))
    assert {WEATHER, CWA, GEE} <= set(ids)
    assert all(record["collection_status"] == "completed" for record in records)
    sources = {source["tool_id"]: source for source in result["sources"]}
    raw_results = {request["tool_id"]: response for request, response in calls}
    snapshots = {tool_id: response["payload"] for tool_id, response in raw_results.items()}
    for tool in (WEATHER, CWA, GEE):
        source = sources[tool]
        raw = snapshots[tool]
        assert source["top_result_summary"]["decision_output"] == raw["decision_output"]
        assert source["missing_fields"] == raw["missing_fields"]
        assert source["runtime_safety_truth"] is False
        assert raw["filters"]["reference_time"] == "2026-06-24T06:00:00+00:00"
        assert raw["decision_output"]["allowed"] is False
        assert raw["decision_output"]["runtimeSafetyTruth"] is False
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    return result, sources


@pytest.mark.parametrize("entrypoint", [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow])
@pytest.mark.parametrize("scenario", ["missing", "partial"])
def test_reported_recent_rain_keeps_candidate_and_all_missing_support(
    tmp_path, weather_tool_calls, entrypoint, scenario,
):
    root = _project(tmp_path, scenario)
    result, sources = _run(root, entrypoint, weather_tool_calls)
    native_weather = sources[WEATHER]["top_result_summary"]["decision_output"]
    output = result["decision_output"]
    assert result["answerability"] == "partial_evidence_with_missing_context"
    assert output["answerSourceToolId"] == WEATHER
    assert output["decision"] == "CHANGE_PLAN" and output["allowed"] is False
    assert output["aggregationRule"] == RULE
    assert output["candidateOnly"] is True and output["humanReviewRequired"] is True
    assert native_weather["firstLayer"]["limit"] in output["firstLayer"]["limit"]
    assert "CWA" in output["firstLayer"]["limit"] and "GEE" in output["firstLayer"]["limit"]
    assert "不得授權出發" in output["firstLayer"]["limit"]
    assert output["firstLayer"]["limit"] in output["text"]
    assert output["firstLayer"]["limit"] in result["answer"]
    assert "使用者回報" in output["firstLayer"]["reason"]
    supporting = {row["toolId"]: row for row in output["supportingDecisions"]}
    missing = {row["tool_id"]: row["missing_fields"] for row in result["missing_evidence"]}
    for tool in (CWA, GEE):
        source = sources[tool]
        assert source["top_result_summary"]["decision"] == "DELAY"
        assert source["missing_fields"]
        assert missing[tool] == source["missing_fields"]
        assert supporting[tool]["decision"] == "DELAY" and supporting[tool]["allowed"] is False
        assert supporting[tool]["missingFields"] == source["missing_fields"]
        for field in source["missing_fields"]:
            assert any(field in value for value in output["requiredConditions"])


@pytest.mark.parametrize("entrypoint", [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow])
@pytest.mark.parametrize("scenario,expected", [
    ("missing-cwa", CWA), ("missing-gee", GEE), ("complete", WEATHER),
    ("cwa-stale", CWA), ("cwa-future", CWA), ("gee-stale", CWA), ("gee-future", CWA),
    ("pressure-cwa-warning", CWA), ("pressure-cwa-qpf", CWA),
    ("pressure-gee-wetness", CWA), ("pressure-gee-rain", CWA),
])
def test_aggregation_does_not_extend_to_mixed_stale_or_measured_pressure(
    tmp_path, weather_tool_calls, entrypoint, scenario, expected,
):
    root = _project(tmp_path, scenario)
    result, sources = _run(root, entrypoint, weather_tool_calls)
    assert result["decision_output"]["answerSourceToolId"] == expected
    assert "aggregationRule" not in result["decision_output"]
    if scenario.endswith(("-stale", "-future")):
        provider = CWA if scenario.startswith("cwa-") else GEE
        gap = "fresh_cwa_environment_evidence" if provider == CWA else "fresh_gee_environment_evidence"
        assert gap in sources[provider]["missing_fields"]
    if scenario.startswith("pressure-"):
        assert sources[CWA]["top_result_summary"]["decision"] == "DELAY"
        assert sources[GEE]["top_result_summary"]["decision"] == "DELAY"


@pytest.mark.parametrize("entrypoint", [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow])
@pytest.mark.parametrize("query,expected", [
    ("午後雷雨是否要改變計畫？溪谷路線天氣如何？", CWA),
    ("預報來源不一致，溪谷路線天氣要如何判斷？", WEATHER),
])
def test_other_weather_decisions_do_not_use_reported_recent_rain_override(
    tmp_path, weather_tool_calls, entrypoint, query, expected,
):
    result, sources = _run(_project(tmp_path, "missing"), entrypoint, weather_tool_calls, query)
    assert result["decision_output"]["answerSourceToolId"] == expected
    assert "aggregationRule" not in result["decision_output"]


@pytest.mark.parametrize("entrypoint", [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow])
@pytest.mark.parametrize("extra,expected", [
    ("可以等霧散再拍照嗎？", "scout.ai.contextual_permission.assess.v0"),
    ("IG 美照看起來很簡單，應該很安全吧？", "scout.ai.media_literacy.assess.v0"),
])
def test_reported_rain_cannot_override_permission_or_media(
    tmp_path, weather_tool_calls, entrypoint, extra, expected,
):
    result, sources = _run(_project(tmp_path, "missing"), entrypoint, weather_tool_calls, RAIN + extra)
    assert expected in sources
    assert result["decision_output"]["answerSourceToolId"] == expected
    assert "aggregationRule" not in result["decision_output"]


@pytest.mark.parametrize("module,metric,boundary", [
    (cwa, "qpf", 30.0), (gee, "wetness", 0.7), (gee, "rain", 80.0),
])
@pytest.mark.parametrize("delta", [-0.001, 0.0, 0.001])
def test_native_pressure_thresholds_remain_unchanged(module, metric, boundary, delta):
    value = boundary + delta
    if metric == "qpf":
        summary = {"warning_count": 0, "observation_count": 0, "qpf_grid_feature_count": 0,
                   "qpf_route_timeline_event_count": 0, "qpf_corridor_summary": {"max_mm": value}}
    else:
        summary = {"smap_timeseries_count": 0, "soil_moisture_grid_feature_count": 0,
                   "gpm_timeseries_count": 0, "antecedent_rain_grid_feature_count": 0,
                   "smap_l4_corridor_summary": {}, "gpm_imerg_corridor_summary": {}}
        container, field = (("smap_l4_corridor_summary", "sm_surface_wetness") if metric == "wetness"
                            else ("gpm_imerg_corridor_summary", "rain_72h_mm"))
        summary[container] = {field: {"latest": value}}
    before = deepcopy(summary)
    assert module._decision_output(summary=summary, missing_fields=[], warnings=[])["decision"] == (
        "CHANGE_PLAN" if delta >= 0 else "REVIEW"
    )
    assert module._decision_output(summary=summary, missing_fields=["fixture_gap"], warnings=[])["decision"] == "DELAY"
    assert summary == before


def _set_native_pressure_artifact(root, metric, value):
    definitions = json.loads(
        (FIXTURES / "weather_workflow/prepared-environment-artifacts.json").read_text()
    )
    path, field = {
        "qpf": (QPF, None), "wetness": (SMAP, "sm_surface_wetness"),
        "rain": (GPM, "rain_72h_mm"),
    }[metric]
    payload = deepcopy(
        definitions["cwa_profiles"]["background"].get(path, definitions["artifacts"][path])
    )
    if metric == "qpf":
        payload["max_mm"] = value
        payload["heavy_rain_event_count"] = 0
    else:
        payload["metrics"][field]["latest"] = value
    _write(root, path, payload)


@pytest.mark.parametrize(
    "entrypoint", [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow]
)
@pytest.mark.parametrize("metric,boundary", [("qpf", 30.0), ("wetness", 0.7), ("rain", 80.0)])
@pytest.mark.parametrize("delta", [-0.001, 0.0, 0.001])
def test_real_partial_pressure_boundary_limits_recent_rain_projection(
    tmp_path, weather_tool_calls, entrypoint, metric, boundary, delta,
):
    root = _project(tmp_path, "partial")
    _set_native_pressure_artifact(root, metric, boundary + delta)
    result, sources = _run(root, entrypoint, weather_tool_calls)
    assert sources[CWA]["top_result_summary"]["decision"] == "DELAY"
    assert sources[GEE]["top_result_summary"]["decision"] == "DELAY"
    assert sources[CWA]["missing_fields"] and sources[GEE]["missing_fields"]
    if delta < 0:
        assert result["decision_output"]["answerSourceToolId"] == WEATHER
        assert result["decision_output"]["aggregationRule"] == RULE
    else:
        assert result["decision_output"]["answerSourceToolId"] == CWA
        assert "aggregationRule" not in result["decision_output"]


@pytest.mark.parametrize(
    "entrypoint", [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow]
)
@pytest.mark.parametrize("metric,value,expected", [("qpf", 30.0, CWA), ("wetness", 0.7, GEE)])
def test_real_measured_environment_change_plan_keeps_opposite_weather_delay(
    tmp_path, weather_tool_calls, entrypoint, metric, value, expected,
):
    root = _project(tmp_path, "complete")
    _set_native_pressure_artifact(root, metric, value)
    query = "前 24 小時降雨、溪水與崩塌，請整理天氣背景。"
    result, sources = _run(root, entrypoint, weather_tool_calls, query)
    assert sources[WEATHER]["top_result_summary"]["decision"] == "DELAY"
    assert sources[expected]["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["answerSourceToolId"] == expected
    assert "aggregationRule" not in result["decision_output"]


def _real_source_objects(tmp_path, weather_tool_calls):
    from scout_ai_answer_synthesis import ScoutAiAnswerSource

    result, _ = _run(
        _project(tmp_path, "missing"), collect_and_synthesize_scout_ai_answer,
        weather_tool_calls,
    )
    return [ScoutAiAnswerSource.model_validate(row) for row in result["sources"]]


@pytest.mark.parametrize("tool_id", [CWA, GEE])
@pytest.mark.parametrize("priority", [4, 6])
def test_synthetic_priority_contract_never_overrides_other_original_order(
    tmp_path, weather_tool_calls, monkeypatch, tool_id, priority,
):
    """Only the priority policy is synthetic; native reader payloads stay untouched."""
    import scout_ai_answer_synthesis as synthesis

    sources = _real_source_objects(tmp_path, weather_tool_calls)
    before = [source.model_dump(mode="json") for source in sources]
    original_priority = synthesis._decision_source_priority

    def different_priority(source, *, question=""):
        rank, identity = original_priority(source, question=question)
        return (priority, identity) if source.tool_id == tool_id else (rank, identity)

    monkeypatch.setattr(synthesis, "_decision_source_priority", different_priority)
    ordered = sorted(sources, key=lambda source: different_priority(source, question=RAIN))
    assert synthesis._reported_recent_rain_missing_support_decision(ordered, question=RAIN) is None
    native_first = next(source for source in ordered if source.top_result_summary.get("decision_output"))
    output = synthesis._answer_decision_output(
        RAIN, sources=sources, missing_evidence=[],
        answerability="partial_evidence_with_missing_context",
    )
    assert output["answerSourceToolId"] == native_first.tool_id
    assert "aggregationRule" not in output
    assert [source.model_dump(mode="json") for source in sources] == before


@pytest.mark.parametrize(
    "metadata", [
        {"collection_status": "failed"},
        {"output_artifact_kind": "synthetic_wrong_weather_kind"},
    ],
)
def test_synthetic_weather_metadata_cannot_enter_recent_rain_rule(
    tmp_path, weather_tool_calls, metadata,
):
    """Deliberately invalid transport metadata is never a native evidence result."""
    import scout_ai_answer_synthesis as synthesis

    originals = _real_source_objects(tmp_path, weather_tool_calls)
    original_snapshot = [source.model_dump(mode="json") for source in originals]
    sources = [
        source.model_copy(deep=True, update=metadata if source.tool_id == WEATHER else {})
        for source in originals
    ]
    before = [source.model_dump(mode="json") for source in sources]
    ordered = sorted(
        sources, key=lambda source: synthesis._decision_source_priority(source, question=RAIN)
    )
    assert synthesis._reported_recent_rain_missing_support_decision(ordered, question=RAIN) is None
    assert [source.model_dump(mode="json") for source in sources] == before
    assert [source.model_dump(mode="json") for source in originals] == original_snapshot


@pytest.mark.parametrize("tool_id", [CWA, GEE])
@pytest.mark.parametrize("operation", ["missing", "duplicate"])
def test_synthetic_missing_or_duplicate_source_cannot_enter_recent_rain_rule(
    tmp_path, weather_tool_calls, tool_id, operation,
):
    """Transport-contract negatives retain all original native snapshots."""
    import scout_ai_answer_synthesis as synthesis

    originals = _real_source_objects(tmp_path, weather_tool_calls)
    original_snapshot = [source.model_dump(mode="json") for source in originals]
    if operation == "missing":
        sources = [source for source in originals if source.tool_id != tool_id]
    else:
        sources = [*originals, next(source for source in originals if source.tool_id == tool_id)]
    ordered = sorted(
        sources, key=lambda source: synthesis._decision_source_priority(source, question=RAIN)
    )
    assert synthesis._reported_recent_rain_missing_support_decision(ordered, question=RAIN) is None
    assert [source.model_dump(mode="json") for source in originals] == original_snapshot


def test_no_evidence_cannot_create_recent_rain_candidate():
    import scout_ai_answer_synthesis as synthesis

    assert synthesis._reported_recent_rain_missing_support_decision([], question=RAIN) is None
