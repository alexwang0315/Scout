from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from tools import scout_ai_six_forces_aihat2_eval as eval_module

from tools.scout_ai_six_forces_aihat2_eval import (
    _plain_excerpt,
    _write_summaries,
    apply_answer_quality_gate,
    assess_six_forces_answer_quality,
    apply_scenario_evidence_overlay,
    canonicalize_output_source_refs,
    runtime_package_versions,
    build_recovery_prompt,
    build_structured_prompt,
    build_three_axis_scorecard,
    compact_evidence_for_model,
    expand_case_runs,
    health_guard,
    parse_model_output,
    quality_tool_results_for_gaps,
    selected_tool_ids,
    snapshot_for_run,
    split_missing_evidence,
    verify_model_output,
)
from tools.scout_ai_aihat2_fallback_eval import (
    _compact_tool_result,
    _contextual_permission_arguments,
    _synthetic_field_context_arguments,
)


def _artifact() -> dict:
    scenarios = [
        {
            "scenario_id": "route.rank-1.v1",
            "source_mode": "synthetic_replay",
            "project_id": "demo",
            "observed_at": "2026-07-16T08:00:00+08:00",
            "boss_point_id": "boss.001",
            "boss_rank": 1,
            "lat": 24.05,
            "lon": 121.22,
            "horizontal_accuracy_m": 5,
            "fix_quality": "synthetic_route_interpolation",
            "route_progress_m": 1000,
            "distance_to_boss_along_route_m": 500,
            "nearest_route_distance_m": 0,
            "heading_deg": 90,
            "travel_direction": "increasing_route_progress",
            "risk_terrain_candidate": {},
            "source_refs": [],
            "condition_overlay_refs": [],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    cases = []
    for force in ("EXP", "RPF", "PER", "RTE", "WTH", "NAV"):
        cases.append(
            {
                "case_id": f"six600.{force}-001.route.rank-1.v1",
                "question_id": f"{force}-001",
                "global_ordinal": len(cases) + 1,
                "force_code": force,
                "force_name": force,
                "capability_name": force,
                "force_ordinal": 1,
                "subsection": "test",
                "question_text": "這裡現在應該怎麼判斷？",
                "question_source_ref": "corpus.md#sha256=x",
                "question_record_sha256": "x",
                "scenario_id": "route.rank-1.v1",
                "expected_evidence_contract": {
                    "required_context": ["scenario_location"],
                    "required_evidence": ["weather"],
                    "scenario_identity_match_required": True,
                    "provenance_required": True,
                    "freshness_required": force in {"PER", "WTH"},
                    "route_intersection_required": force in {"PER", "WTH"},
                    "missing_semantics": "unknown_not_permission",
                    "candidate_status_policy": "candidate_must_remain_unconfirmed",
                    "required_answer_elements": [
                        "decisive_evidence",
                        "opposing_evidence",
                        "evidence_gaps",
                        "decision_change_conditions",
                        "source_refs",
                    ],
                },
                "expected_decision_boundary": {
                    "answer_mode": "decision" if force in {"PER", "WTH"} else "compound",
                    "allowed_decisions": ["GO", "CHANGE_PLAN", "DELAY"],
                    "forbidden_claims": ["guaranteed safe"],
                },
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return {"project_id": "demo", "scenarios": scenarios, "cases": cases}


def test_expands_every_permission_and_weather_case_to_three_contexts() -> None:
    runs = expand_case_runs(_artifact())

    assert len(runs) == 10
    assert len([item for item in runs if item["force_code"] == "PER"]) == 3
    assert len([item for item in runs if item["force_code"] == "WTH"]) == 3
    assert len({item["run_case_id"] for item in runs}) == 10


def test_per095_uses_exact_three_context_decision_boundaries() -> None:
    artifact = _artifact()
    permission_case = next(
        item for item in artifact["cases"] if item["force_code"] == "PER"
    )
    permission_case["question_id"] = "PER-095"
    permission_case["case_id"] = "six600.PER-095.route.rank-1.v1"

    runs = [item for item in expand_case_runs(artifact) if item["force_code"] == "PER"]

    assert {item["variant_id"]: item["expected_decisions"] for item in runs} == {
        "exposed_strong_wind_shelter_ahead": ["CHANGE_PLAN"],
        "sheltered_flat_time_available": ["CONDITIONAL_GO"],
        "gnss_stale_location_unknown": ["DELAY"],
    }


def test_stale_permission_context_does_not_claim_location() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "gnss_stale_location_unknown"
    )

    snapshot = snapshot_for_run(run)

    assert snapshot["scenario_id"] == run["scenario_id"]
    assert snapshot["fix_quality"] == "stale_unknown"
    assert "lat" not in snapshot
    assert "route_progress_m" not in snapshot


def test_structured_prompt_excludes_reference_and_allowed_decisions() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "PER")
    prompt = build_structured_prompt(
        run=run,
        compact_evidence={"scenario_id": run["scenario_id"], "source_refs": ["a.json"]},
    )

    assert "deterministic_reference" not in prompt
    assert "allowed_decisions" not in prompt
    assert run["question_text"] in prompt
    assert "candidate_only" in prompt
    assert "a 必須至少保留" in prompt


def test_structured_prompt_uses_missing_evidence_response_mode_without_reference() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")

    prompt = build_structured_prompt(
        run=run,
        compact_evidence={
            "scenario_id": run["scenario_id"],
            "missing_evidence": ["question_specific_route_context_evidence_missing"],
            "tools": [],
        },
    )

    assert "工作區未提供足夠的題目專屬證據，無法確認" in prompt
    assert "deterministic_reference" not in prompt


def test_cloud_structured_prompt_removes_local_hint_and_uses_native_tool_catalog() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    prompt = build_structured_prompt(
        run=run,
        compact_evidence={
            "scenario_id": run["scenario_id"],
            "tools": [
                {
                    "tool_id": "tool.one",
                    "status": "completed",
                    "field_answer": "must arrive through a tool return",
                },
                {"tool_id": "tool.two", "status": "completed"},
            ],
        },
        model_profile="cloud",
    )

    assert "/no_think" not in prompt
    assert "本地模型" not in prompt
    assert "Pydantic AI native tools" in prompt
    assert "tool.one" in prompt
    assert "tool.two" in prompt
    assert "must arrive through a tool return" not in prompt


def test_parser_extracts_json_and_verifier_checks_scenario() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "PER")
    raw = "result:\n" + json.dumps(
        {
            "scenario_id": run["scenario_id"],
            "decision": "CHANGE_PLAN",
            "answer": "先移動到前方背風候選點再評估。",
            "decisive_evidence": ["強風且目前為暴露候選地形"],
            "opposing_evidence": ["仍有時間緩衝"],
            "evidence_gaps": [],
            "decision_change_conditions": ["風勢下降且確認背風平坦"],
            "source_refs": ["a.json"],
            "claims": ["candidate evidence only"],
        },
        ensure_ascii=False,
    )
    parsed, error = parse_model_output(raw)
    verified = verify_model_output(
        run=run,
        output=parsed,
        parse_error=error,
        available_source_refs={"a.json"},
    )

    assert error is None
    assert verified["status"] == "pass"


def test_permission_verifier_rejects_claim_that_shelter_path_does_not_exist() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "PER")
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "NO_GO",
        "answer": "不能停留，因為前方沒有安全路徑。",
        "decisive_evidence": ["強風"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": [],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert "contradicts_sheltered_candidate_ahead" in verified["errors"]


def test_exposed_permission_verifier_accepts_tool_grounded_retreat_answer() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "exposed_strong_wind_shelter_ahead"
    )
    run["question_id"] = "PER-071"
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "GO",
        "answer": "建議立即撤退，前往最近安全點並保持隊伍完整。",
        "decisive_evidence": ["暴露地形且撤退可降低後續不確定性"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": ["撤退路徑不可用"],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.contextual_permission.assess.v0",
                    "decision": "GO",
                }
            ]
        },
    )

    assert verified["status"] == "pass"


def test_permission_verifier_accepts_bounded_eight_minute_stop_answer() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "sheltered_flat_time_available"
    )
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "CONDITIONAL_GO",
        "answer": "目前可以，最多 8 分鐘，時間到就離開。",
        "decisive_evidence": ["背風平坦且有時間 buffer"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": ["風勢增強"],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert verified["status"] == "pass"


def test_permission_verifier_accepts_simplified_chinese_minute_grounding() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "sheltered_flat_time_available"
    )
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "CONDITIONAL_GO",
        "answer": "目前可行，在此 8 分钟後離開。",
        "decisive_evidence": ["背風平坦且有時間 buffer"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": ["風勢增強"],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert verified["status"] == "pass"


def test_permission_fixture_uses_scenario_time_buffer_as_single_source() -> None:
    arguments = _contextual_permission_arguments(
        {
            "variant_id": "sheltered_flat_time_available",
            "time_buffer_minutes": 48,
        },
        observed_at="2026-07-20T02:37:25+00:00",
    )

    assert arguments["remaining_safety_buffer_minutes"] == 48


def test_permission_verifier_accepts_primary_tool_no_go_for_inherently_risky_action() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "sheltered_flat_time_available"
    )
    run["question_id"] = "PER-024"
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "NO_GO",
        "answer": "不能離開主徑走到旁邊岩石；請留在原路線。",
        "decisive_evidence": ["primary permission tool rejects leaving route"],
        "opposing_evidence": ["背風平坦且有時間 buffer"],
        "evidence_gaps": [],
        "decision_change_conditions": ["取得已審核替代路線"],
        "source_refs": ["scout.ai.contextual_permission.assess.v0"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"scout.ai.contextual_permission.assess.v0"},
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.contextual_permission.assess.v0",
                    "decision": "NO_GO",
                }
            ]
        },
    )

    assert verified["status"] == "pass"


def test_quality_accepts_grounded_primary_tool_no_go_as_an_answer() -> None:
    quality = assess_six_forces_answer_quality(
        "不建議走支線；缺少已審核替代路線，請留在原路線。",
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {
                "tool_id": "scout.ai.contextual_permission.assess.v0",
                "decision": "NO_GO",
                "field_answer": (
                    "不建議走支線；缺少已審核替代路線，請留在原路線。"
                ),
            }
        ],
    )

    assert quality["classification"] == "auto_screen_pass_requires_human_review"
    assert quality["failure_reasons"] == []
    assert quality["grounding_match_method"] == "primary_field_answer_overlap"


def test_verifier_rejects_answer_text_that_contradicts_decision_enum() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "WTH"
        and item["variant_id"] == "benign_fresh_route_intersecting"
    )
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "CHANGE_PLAN",
        "answer": "NO_GO",
        "decisive_evidence": ["弱風"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": [],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert "answer_decision_contradiction" in verified["errors"]


def test_verifier_allows_subordinate_tool_decision_inside_overall_delay_answer() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "RPF")
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "DELAY",
        "answer": (
            "日落時間未知，先補齊日照資料後再判斷；腳程守門員另建議 "
            "CHANGE_PLAN，因後隊儲備不足。"
        ),
        "decisive_evidence": ["日照資料缺失"],
        "opposing_evidence": ["Pace Guardian 建議 CHANGE_PLAN"],
        "evidence_gaps": ["reviewed_daylight_window"],
        "decision_change_conditions": ["取得日落與 ETA"],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert "answer_decision_contradiction" not in verified["errors"]


def test_verifier_allows_conservative_decision_supported_by_compound_evidence() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "WTH"
        and item["variant_id"] == "benign_fresh_route_intersecting"
    )
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "DELAY",
        "answer": "天氣本身良好，但地形風險工具仍建議延後通過。",
        "decisive_evidence": ["risk tool returns NO_GO"],
        "opposing_evidence": ["weather tool returns CONDITIONAL_GO"],
        "evidence_gaps": [],
        "decision_change_conditions": ["地形風險解除後重判"],
        "source_refs": ["risk-tool", "weather-tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"risk-tool", "weather-tool"},
        compact_evidence={
            "tools": [
                {"tool_id": "weather-tool", "decision": "CONDITIONAL_GO"},
                {"tool_id": "risk-tool", "decision": "NO_GO"},
            ]
        },
    )

    assert "decision_outside_scenario_boundary" not in verified["errors"]


def test_verifier_requires_route_shape_answer_for_rte001() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "RTE")
    run["question_id"] = "RTE-001"
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "CHANGE_PLAN",
        "answer": "路線有需要以 CP 為單位監控的難點。",
        "decisive_evidence": ["CP Graph"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": [],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert "route_shape_not_answered" in verified["errors"]


def test_parser_expands_compact_local_model_schema() -> None:
    parsed, error = parse_model_output(
        '{"s":"scenario.1","d":"DELAY","a":"先等候","e":"定位過期",'
        '"o":"","g":"GNSS stale","c":"定位恢復","r":"tool.id","cl":"candidate_only"}'
    )

    assert error is None
    assert parsed == {
        "scenario_id": "scenario.1",
        "decision": "DELAY",
        "answer": "先等候",
        "decisive_evidence": ["定位過期"],
        "opposing_evidence": [],
        "evidence_gaps": ["GNSS stale"],
        "decision_change_conditions": ["定位恢復"],
        "source_refs": ["tool.id"],
        "claims": ["candidate_only"],
    }


def test_parser_normalizes_hailo_fullwidth_quotes_and_source_prefix() -> None:
    parsed, error = parse_model_output(
        "{＂s＂:＂scenario.1＂,＂d＂:null,＂a＂:＂短答＂,＂e＂:＂證據＂,"
        "＂o＂:＂＂,＂g＂:＂＂,＂c＂:＂條件＂,＂r＂:＂tool_id：scout.ai.route_context.assess.v0＂,"
        "＂cl＂:＂candidate_only＂}"
    )

    assert error is None
    assert parsed["source_refs"] == ["scout.ai.route_context.assess.v0"]


def test_parser_strips_hailo_whitespace_from_compact_json_keys() -> None:
    parsed, error = parse_model_output(
        '{"s":"scenario.1","d":null,"a":"稜線啞口觀景點值得理解",'
        '" e":"候選路線脈絡","o":"","g":"","c":"天候轉差",'
        '"r":"scout.ai.route_context.assess.v0"," cl":"candidate_only"}'
    )

    assert error is None
    assert parsed["decisive_evidence"] == ["候選路線脈絡"]
    assert parsed["claims"] == ["candidate_only"]


def test_parser_defaults_omitted_optional_evidence_lists() -> None:
    parsed, error = parse_model_output(
        '{"s":"scenario.1","d":null,"a":"稜線啞口觀景點值得理解",'
        '"e":"候選路線脈絡"}'
    )

    assert error is None
    assert parsed["opposing_evidence"] == []
    assert parsed["evidence_gaps"] == []
    assert parsed["decision_change_conditions"] == []
    assert parsed["source_refs"] == []
    assert parsed["claims"] == []


def test_parser_repairs_hailo_backslash_escaped_array_quotes() -> None:
    parsed, error = parse_model_output(
        '{"s":"scenario.1","d":null,"a":"短答",'
        '"g":[\\"candidate_only\\",\\"location\\"]"}'
    )

    assert error is None
    assert parsed["evidence_gaps"] == ["candidate_only", "location"]


def test_parser_repairs_hailo_missing_quote_for_empty_evidence_value() -> None:
    parsed, error = parse_model_output(
        '{＂s＂:＂scenario.1＂,＂d＂:＂CONDITIONAL_GO＂,＂a＂:＂O 型候選＂,'
        '＂e＂:＂端點相距 95.6 m＂,＂o＂:＂,＂g＂:＂＂,＂c＂:＂重疊分析＂,'
        '＂r＂:＂scout.ai.route_architecture.assess.v0＂,＂cl＂:＂candidate_only＂}'
    )

    assert error is None
    assert parsed["opposing_evidence"] == []
    assert parsed["answer"] == "O 型候選"


def test_full_artifact_expands_to_one_thousand_when_available() -> None:
    path = Path(
        "/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/"
        "scout_ai_six_forces_600_scenarios.json"
    )
    if not path.exists():
        return

    runs = expand_case_runs(json.loads(path.read_text(encoding="utf-8")))

    assert len(runs) == 1000
    assert len({item["question_id"] for item in runs}) == 600
    assert len({item["run_case_id"] for item in runs}) == 1000


def test_health_guard_warns_on_historical_flags_but_fails_current_flags() -> None:
    historical = health_guard(
        {
            "temp": {"stdout": "temp=56.5'C"},
            "throttled": {"stdout": "throttled=0x50000"},
            "ups": {"power_supplies": []},
        }
    )
    current = health_guard(
        {
            "temp": {"stdout": "temp=56.5'C"},
            "throttled": {"stdout": "throttled=0x50005"},
            "ups": {"power_supplies": []},
        }
    )

    assert historical["status"] == "warn"
    assert current["status"] == "fail"


@pytest.mark.parametrize(
    (
        "adapter_id",
        "profile",
        "provider",
        "transport",
        "endpoint",
        "model",
    ),
    (
        (
            "openrouter.pydantic_ai",
            "cloud",
            "openrouter",
            "pydantic_ai_openrouter",
            "https://openrouter.ai/api/v1",
            "openrouter:deepseek/deepseek-v4-flash",
        ),
        (
            "ai_hat_plus_2.hailo_ollama",
            "local",
            "hailo_ollama_ai_hat_plus_2",
            "pydantic_ai_function_model_hailo_ollama",
            "http://127.0.0.1:8000/api/chat",
            "qwen3:1.7b",
        ),
    ),
)
def test_execute_run_uses_provider_neutral_model_adapter(
    monkeypatch,
    adapter_id: str,
    profile: str,
    provider: str,
    transport: str,
    endpoint: str,
    model: str,
) -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    snapshot = snapshot_for_run(run)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(eval_module, "selected_tool_ids", lambda **_: ["tool.ref"])
    monkeypatch.setattr(
        eval_module,
        "build_total_info",
        lambda *_args, **_kwargs: {
            "location_context": {"live_navigation_snapshot": snapshot}
        },
    )
    monkeypatch.setattr(
        eval_module,
        "run_tools",
        lambda **_: (
            [
                {
                    "tool_id": "tool.ref",
                    "status": "completed",
                    "field_answer": "工作區只提供候選路線脈絡。",
                    "field_answer_priority": 100,
                    "field_answer_source_ref": "tool.ref",
                }
            ],
            [],
            [],
        ),
    )

    def fake_model_call(**kwargs):
        calls.append(kwargs)
        return (
            json.dumps(
                {
                    "s": run["scenario_id"],
                    "d": None,
                    "a": "目前只能確認候選路線脈絡，仍需核對題目專屬證據。",
                    "e": "工作區候選證據",
                    "g": "題目專屬證據待核對",
                    "r": "tool.ref",
                    "cl": "candidate_only",
                },
                ensure_ascii=False,
            ),
            {"usage": {"input_tokens": 100, "output_tokens": 40}},
        )

    model_adapter = eval_module.ScoutModelExecutionAdapter(
        adapter_id=adapter_id,
        profile=profile,
        provider=provider,
        transport=transport,
        invoke=fake_model_call,
    )
    result = eval_module.execute_run(
        run=run,
        project_root=Path("/tmp/demo"),
        endpoint=endpoint,
        model=model,
        timeout_seconds=30,
        max_model_requests=10,
        guided_retry=False,
        model_adapter=model_adapter,
    )

    assert len(calls) == 1
    assert calls[0]["model"] == model
    assert result["model_adapter_id"] == adapter_id
    assert result["model_profile"] == profile
    assert result["provider"] == provider
    assert result["model_transport"] == transport
    assert result["model_metadata"]["usage"]["input_tokens"] == 100


def test_shared_executor_requires_explicit_model_adapter() -> None:
    parameter = inspect.signature(eval_module.execute_run).parameters["model_adapter"]

    assert parameter.default is inspect.Parameter.empty


def test_aihat_entrypoint_builds_explicit_local_model_adapter() -> None:
    adapter = eval_module.build_ai_hat_plus_2_model_adapter()

    assert adapter.adapter_id == "ai_hat_plus_2.hailo_ollama"
    assert adapter.profile == "local"
    assert adapter.provider == "hailo_ollama_ai_hat_plus_2"
    assert adapter.transport == "pydantic_ai_function_model_hailo_ollama"


def test_tool_adapter_preserves_top_level_field_answer_with_result_records() -> None:
    compact = _compact_tool_result(
        {
            "tool_id": "scout.ai.route_context.assess.v0",
            "status": "completed",
            "payload": {
                "answerability": "route_context_available",
                "field_answer": "15K 位於候選 CP-015 附近。",
                "field_answer_priority": 100,
                "field_answer_source_ref": "candidates/route_mileage_k_anchors.json",
                "results": [{"label": "15K", "source_path": "anchors.json"}],
            },
        }
    )

    assert compact["field_answer"] == "15K 位於候選 CP-015 附近。"
    assert compact["field_answer_priority"] == 100
    assert compact["field_answer_source_ref"] == "candidates/route_mileage_k_anchors.json"


def test_compact_evidence_marks_low_priority_route_context_as_gap() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    evidence = compact_evidence_for_model(
        run=run,
        total_info=None,
        tool_results=[
            {
                "tool_id": "scout.ai.route_context.assess.v0",
                "status": "completed",
                "answerability": "route_context_available",
                "field_answer": "只有泛用候選點。",
                "field_answer_priority": 0,
                "field_answer_source_ref": "candidates/route_context_points.json",
                "records": [{"label": "203", "context_kind": "route_context"}],
            }
        ],
        missing_tools=[],
        missing_evidence=[],
    )

    assert "question_specific_route_context_evidence_missing" in evidence["missing_evidence"]
    assert evidence["tools"][0]["field_answer"] == "只有泛用候選點。"


def test_cloud_evidence_keeps_all_relevant_cards_without_1600_character_packing() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "RPF")
    tool_results = [
        {
            "tool_id": f"tool.{index}",
            "status": "completed",
            "field_answer": f"card {index} " + ("證據" * 300),
            "field_answer_priority": 100 - index,
            "records": [{"index": index, "payload": "資料" * 300}],
        }
        for index in range(6)
    ]

    evidence = compact_evidence_for_model(
        run=run,
        total_info=None,
        tool_results=tool_results,
        missing_tools=[],
        missing_evidence=[],
        max_chars=None,
    )

    assert [item["tool_id"] for item in evidence["tools"]] == [
        f"tool.{index}" for index in range(6)
    ]
    assert evidence["packing"] == {
        "mode": "full_relevant_evidence_cards",
        "omitted_tool_count": 0,
        "max_chars": None,
    }
    assert len(json.dumps(evidence, ensure_ascii=False)) > 1600


def test_fresh_weather_overlay_replaces_stale_primary_weather_gap() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "WTH"
        and item["variant_id"] == "benign_fresh_route_intersecting"
    )
    tools, missing = apply_scenario_evidence_overlay(
        run=run,
        tool_results=[
            {
                "tool_id": "scout.ai.weather_window.assess.v0",
                "status": "completed",
                "decision": "DELAY",
                "field_answer": "舊 workspace 天氣已過期。",
                "missing_fields": ["fresh_route_weather_evidence"],
            }
        ],
        missing_evidence=[
            "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence",
            "scout.ai.cwa_environment.assess.v0:missing:fresh_cwa_environment_evidence",
        ],
    )

    assert tools[0]["decision"] == "CONDITIONAL_GO"
    assert "良好天氣 synthetic replay" in tools[0]["field_answer"]
    assert tools[0]["missing_fields"] == []
    assert (
        "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence"
        not in missing
    )
    assert "scout.ai.cwa_environment.assess.v0:missing:fresh_cwa_environment_evidence" in missing


def test_stale_weather_overlay_preserves_primary_weather_gap() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "WTH"
        and item["variant_id"] == "stale_unknown_weather"
    )
    tools, missing = apply_scenario_evidence_overlay(
        run=run,
        tool_results=[
            {"tool_id": "scout.ai.weather_window.assess.v0", "status": "completed"}
        ],
        missing_evidence=[],
    )

    assert tools[0]["decision"] == "DELAY"
    assert tools[0]["missing_fields"] == ["fresh_route_weather_evidence"]
    assert missing == [
        "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence"
    ]


def test_verifier_rejects_unsupported_factual_claim_when_specific_evidence_is_missing() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    output = {
        "scenario_id": run["scenario_id"],
        "decision": None,
        "answer": "這座山主要由花崗岩構成。",
        "decisive_evidence": ["花崗岩"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": ["取得地質圖"],
        "source_refs": ["scout.ai.route_context.assess.v0"],
        "claims": ["candidate_only"],
    }
    evidence = {
        "missing_evidence": ["question_specific_route_context_evidence_missing"],
        "tools": [
            {
                "tool_id": "scout.ai.route_context.assess.v0",
                "field_answer": "只有泛用候選點。",
                "record": "203 route_context",
            }
        ],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"scout.ai.route_context.assess.v0"},
        compact_evidence=evidence,
    )

    assert "unsupported_answer_despite_question_specific_evidence_gap" in verified["errors"]
    assert "missing_evidence_not_preserved" in verified["errors"]


def test_recovery_prompt_carries_verifier_feedback_without_reference_answer() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    evidence = {
        "scenario_id": run["scenario_id"],
        "missing_evidence": ["question_specific_route_context_evidence_missing"],
        "tools": [],
    }

    prompt = build_recovery_prompt(
        run=run,
        compact_evidence=evidence,
        previous_output={"answer": "山體由花崗岩構成。"},
        verifier_errors=["unsupported_answer_despite_question_specific_evidence_gap"],
    )

    assert "unsupported_answer_despite_question_specific_evidence_gap" in prompt
    assert "工作區未提供" in prompt
    assert "deterministic_reference" not in prompt
    assert "allowed_decisions" not in prompt
    assert prompt.rstrip().endswith('"cl":"candidate_only"}')
    assert f'"s":"{run["scenario_id"]}"' in prompt
    assert "山體由花崗岩構成" in prompt
    assert '"scenario_id"' not in prompt
    repair_candidate = prompt.rsplit("correction candidate", maxsplit=1)[-1]
    assert "工作區未提供足夠的題目專屬證據" in repair_candidate
    assert "question_specific_route_context_evidence_missing" in repair_candidate
    assert "山體由花崗岩構成" not in repair_candidate


def test_recovery_prompt_replaces_unsupported_answer_with_primary_field_answer() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    field_answer = "候選路線脈絡包含稜線啞口觀景點、雲海保線所與黑水塘。"
    evidence = {
        "scenario_id": run["scenario_id"],
        "missing_evidence": [],
        "tools": [
            {
                "tool_id": "scout.ai.route_context.assess.v0",
                "decision": "CONDITIONAL_GO",
                "field_answer": field_answer,
            }
        ],
    }

    prompt = build_recovery_prompt(
        run=run,
        compact_evidence=evidence,
        previous_output={"answer": "路線僅有登頂，沒有其他內容。"},
        verifier_errors=["answer_quality:did_not_preserve_expected_tool_tokens"],
    )

    repair_candidate = prompt.rsplit("correction candidate", maxsplit=1)[-1]
    assert field_answer in repair_candidate
    assert "路線僅有登頂" not in repair_candidate


def test_recovery_prompt_replaces_answer_when_sheltered_next_step_is_missing() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "exposed_strong_wind_shelter_ahead"
    )
    field_answer = "不要原地等待；前往約 180 公尺外的前方背風候選點後重評。"
    prompt = build_recovery_prompt(
        run=run,
        compact_evidence={
            "scenario_id": run["scenario_id"],
            "tools": [
                {
                    "tool_id": "scout.ai.contextual_permission.assess.v0",
                    "decision": "CHANGE_PLAN",
                    "field_answer": field_answer,
                }
            ],
        },
        previous_output={"decision": "CHANGE_PLAN", "answer": "會犧牲 35 分鐘 buffer。"},
        verifier_errors=["missing_sheltered_candidate_next_step"],
    )

    repair_candidate = prompt.rsplit("correction candidate", maxsplit=1)[-1]
    assert field_answer in repair_candidate
    assert "會犧牲 35 分鐘 buffer" not in repair_candidate


def test_summary_requires_verifier_and_quality_acceptance(tmp_path: Path) -> None:
    base = {
        "context_identity_check": {"status": "pass"},
        "failure_category": None,
        "force": "NAV",
        "decision": "GO",
        "model_request_count": 1,
        "duration_ms": 250,
        "model_attempts": [
            {
                "model_metadata": {
                    "usage": {"input_tokens": 100, "output_tokens": 25, "requests": 1}
                }
            }
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    results = [
        {
            **base,
            "question_id": "NAV-001",
            "verifier": {"status": "pass"},
            "answer_quality_screen": {
                "classification": "auto_screen_pass_requires_human_review"
            },
        },
        {
            **base,
            "question_id": "NAV-002",
            "verifier": {"status": "pass"},
            "answer_quality_screen": {"classification": "quality_fail"},
        },
        {
            **base,
            "question_id": "NAV-003",
            "verifier": {"status": "fail"},
            "answer_quality_screen": {"classification": "quality_needs_review"},
        },
        {
            **base,
            "question_id": "NAV-004",
            "failure_category": "missing_evidence",
            "blocking_missing_evidence": ["fresh_gnss_fix"],
            "verifier": {"status": "pass"},
            "answer_quality_screen": {"classification": "quality_needs_review"},
        },
    ]
    manifest = {
        "run_id": "test",
        "model": "qwen3:1.7b",
        "provider": "hailo_ollama_ai_hat_plus_2",
    }

    _write_summaries(tmp_path, manifest, results)

    summary = json.loads((tmp_path / "model_summary.json").read_text())
    assert summary["strict_answer_summary"] == {"accepted": 2, "rejected": 2}
    assert summary["model_usage_totals"] == {
        "input_tokens": 400,
        "output_tokens": 100,
        "requests": 4,
    }
    assert summary["total_duration_ms"] == 1000
    assert summary["failure_count"] == 1
    assert summary["blocking_evidence_gap_count"] == 1
    assert summary["quality_review_count"] == 2
    assert summary["quality_review_reason_summary"] == {}
    assert len(json.loads((tmp_path / "failures.json").read_text())) == 1
    assert len(json.loads((tmp_path / "evidence_gap_reviews.json").read_text())) == 1
    assert "strict verifier + quality acceptance: `2/4`" in (
        tmp_path / "summary.md"
    ).read_text()


def test_quality_gate_rejects_ungrounded_answer_when_evidence_is_sufficient() -> None:
    verifier = apply_answer_quality_gate(
        {"status": "pass", "errors": []},
        {
            "classification": "quality_fail",
            "failure_reasons": ["did_not_preserve_expected_tool_tokens"],
        },
        evidence_sufficient=True,
    )

    assert verifier["status"] == "fail"
    assert verifier["errors"] == [
        "answer_quality:did_not_preserve_expected_tool_tokens"
    ]


def test_six_forces_quality_accepts_concise_primary_field_grounding() -> None:
    quality = assess_six_forces_answer_quality(
        "前往約 180 公尺外的前方背風候選點，抵達後重新評估。",
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {
                "tool_id": "scout.ai.contextual_permission.assess.v0",
                "field_answer": (
                    "不要在此停留；維持在已知路線走廊內，前往約 180 公尺外的"
                    "前方背風候選點，抵達後重新評估。"
                ),
            }
        ],
    )

    assert quality["classification"] == "auto_screen_pass_requires_human_review"
    assert quality["failure_reasons"] == []
    assert quality["grounded_context_use"] is True
    assert quality["grounding_match_method"] == "primary_field_answer_overlap"


def test_six_forces_quality_keeps_grounded_gap_answer_for_review() -> None:
    quality = assess_six_forces_answer_quality(
        "GNSS/GPS 定位已過期，先重新取得定位再判斷。",
        missing_tools=[],
        blocking_missing_evidence=[
            "scout.ai.contextual_permission.assess.v0:missing:remaining_safety_buffer_minutes"
        ],
        tool_results=[
            {
                "tool_id": "scout.ai.contextual_permission.assess.v0",
                "field_answer": "GNSS/GPS 定位已過期或目前位置未知，重新取得定位後再判斷。",
            }
        ],
    )

    assert quality["classification"] == "quality_needs_review"
    assert quality["grounded_context_use"] is True
    assert quality["failure_reasons"] == ["missing_evidence_gap"]
    assert quality["grounding_match_method"] == "primary_field_answer_overlap"


def test_six_forces_quality_accepts_grounded_tool_level_gap_as_safe_uncertainty() -> None:
    quality = assess_six_forces_answer_quality(
        (
            "現有證據無法確認傳統獵徑；主要點查詢沒有匹配點，"
            "路線結構工具亦執行失敗。"
        ),
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {
                "tool_id": "route.context",
                "status": "completed",
                "answerability": "route_context_available",
                "field_answer": "黑水塘與雲海保線所是候選路線脈絡。",
            },
            {
                "tool_id": "route.structure",
                "status": "failed",
                "field_answer": None,
            },
            {
                "tool_id": "major.points",
                "status": "completed",
                "answerability": "major_points_missing_evidence",
                "field_answer": "主要點查詢沒有匹配點。",
            },
        ],
    )

    assert quality["classification"] == "quality_needs_review"
    assert quality["failure_reasons"] == ["tool_evidence_gap"]
    assert quality["grounding_match_method"] == "tool_field_answer_overlap"


def test_six_forces_quality_rejects_generic_answer_without_primary_grounding() -> None:
    quality = assess_six_forces_answer_quality(
        "前往下一個安全 CP。",
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {
                "tool_id": "scout.ai.contextual_permission.assess.v0",
                "field_answer": "目前可有條件停留，最多 8 分鐘，之後必須離開。",
            }
        ],
    )

    assert quality["classification"] == "quality_fail"
    assert "did_not_preserve_expected_tool_tokens" in quality["failure_reasons"]


def test_six_forces_quality_accepts_grounding_from_complete_tool_card() -> None:
    quality = assess_six_forces_answer_quality(
        "不適合前進；大雨、強風、低能見度與 99.54 極端風險同時出現。",
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {
                "tool_id": "weather.tool",
                "decision": "CHANGE_PLAN",
                "field_answer": "signals=heavy_rain,strong_wind,low_visibility",
                "records": [{"max_score": 99.54, "risk_bucket": "extreme"}],
            }
        ],
    )

    assert quality["classification"] == "auto_screen_pass_requires_human_review"
    assert quality["failure_reasons"] == []
    assert quality["grounded_context_use"]


def test_plain_excerpt_keeps_string_newlines_natural_and_finishes_nearby_sentence() -> None:
    value = (
        "[決策] 可以，最多 8 分鐘。\n"
        "[限制] 必須在時限前離開。\n"
        "[原因] 背風且地形平坦，仍需保留安全 buffer。\n"
        "[下一步] 到時限後立即離開，前往下一個安全 CP。"
    )

    excerpt = _plain_excerpt(value, 72)

    assert " n " not in excerpt
    assert "\n" not in excerpt
    assert excerpt.endswith("安全 CP。")


def test_runtime_package_versions_attest_pydantic_ai_stack() -> None:
    versions = runtime_package_versions()

    assert versions["pydantic_ai_slim"] == "2.14.1"
    assert versions["pydantic_evals"] == "2.14.1"
    assert versions["pydantic_graph"] == "2.14.1"


def test_three_axis_scorecard_separates_transport_safety_and_semantics() -> None:
    scorecard = build_three_axis_scorecard(
        output={
            "scenario_id": "scenario.1",
            "decision": None,
            "answer": "CP-12 距離約 180 公尺，應先核對路線候選證據。",
            "decisive_evidence": ["CP-12 約 180 公尺"],
            "opposing_evidence": [],
            "evidence_gaps": [],
            "decision_change_conditions": ["定位更新"],
            "source_refs": ["tool.one", "tool.two"],
            "claims": ["candidate_only"],
        },
        parse_error=None,
        identity={"status": "pass", "errors": []},
        verifier={"status": "pass", "errors": []},
        model_metadata={
                "native_tool_trace": {
                    "tool_call_count": 2,
                    "tool_return_count": 2,
                    "offered_tool_ids": ["tool.one", "tool.two"],
                    "called_tool_ids": ["tool.one", "tool.two"],
            }
        },
        native_tool_call_required=True,
        available_source_refs={"tool.one", "tool.two"},
        completed_tools=["tool.one", "tool.two"],
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {"tool_id": "tool.one", "field_answer": "CP-12 距離約 180 公尺。"},
            {"tool_id": "tool.two", "field_answer": "需核對路線候選證據。"},
        ],
    )

    assert scorecard["transport_schema"]["score"] == 100
    assert scorecard["safe_uncertainty"]["score"] == 100
    assert scorecard["semantic_answer_quality"]["score"] == 100


def test_three_axis_scorecard_accepts_grounding_from_complete_tool_card_records() -> None:
    scorecard = build_three_axis_scorecard(
        output={
            "scenario_id": "scenario.1",
            "decision": "CHANGE_PLAN",
            "answer": "風險最高為 99.54，位置靠近雲海保線所。",
            "decisive_evidence": ["risk score"],
            "opposing_evidence": [],
            "evidence_gaps": [],
            "decision_change_conditions": ["風險更新"],
            "source_refs": ["tool.one"],
            "claims": ["candidate_only"],
        },
        parse_error=None,
        identity={"status": "pass", "errors": []},
        verifier={"status": "pass", "errors": []},
        model_metadata={
            "native_tool_trace": {
                "tool_call_count": 1,
                "tool_return_count": 1,
                "offered_tool_ids": ["tool.one"],
                "called_tool_ids": ["tool.one"],
            }
        },
        native_tool_call_required=True,
        available_source_refs={"tool.one"},
        completed_tools=["tool.one"],
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {
                "tool_id": "tool.one",
                "field_answer": "已完成風險查詢。",
                "records": [{"score": 99.54, "name": "雲海保線所"}],
            }
        ],
    )

    assert scorecard["semantic_answer_quality"]["components"][
        "workspace_evidence_grounding"
    ]
    assert scorecard["semantic_answer_quality"]["score"] == 100


def test_three_axis_scorecard_does_not_call_generic_schema_valid_answer_semantic_success() -> None:
    scorecard = build_three_axis_scorecard(
        output={
            "scenario_id": "scenario.1",
            "decision": None,
            "answer": "請提供更多資訊。",
            "decisive_evidence": [],
            "opposing_evidence": [],
            "evidence_gaps": [],
            "decision_change_conditions": [],
            "source_refs": ["tool.one"],
            "claims": ["candidate_only"],
        },
        parse_error=None,
        identity={"status": "pass", "errors": []},
        verifier={"status": "pass", "errors": []},
        model_metadata={
                "native_tool_trace": {
                    "tool_call_count": 1,
                    "tool_return_count": 1,
                    "offered_tool_ids": ["tool.one"],
                    "called_tool_ids": ["tool.one"],
            }
        },
        native_tool_call_required=True,
        available_source_refs={"tool.one"},
        completed_tools=["tool.one"],
        missing_tools=[],
        blocking_missing_evidence=[],
        tool_results=[
            {"tool_id": "tool.one", "field_answer": "CP-12 距離約 180 公尺。"}
        ],
    )

    assert scorecard["transport_schema"]["score"] == 100
    assert scorecard["semantic_answer_quality"]["score"] < 60


def test_selected_tools_put_force_primary_before_planner_and_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        eval_module,
        "plan_scout_ai_tools",
        lambda *args, **kwargs: SimpleNamespace(
            selected_tools=[
                SimpleNamespace(tool_id="scout.ai.energy_vitals.assess.v0"),
                SimpleNamespace(tool_id="scout.ai.pace_guardian.assess.v0"),
            ]
        ),
    )
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="以我過去的紀錄，這條路線符合我的腳程嗎？",
        project_id="demo",
    )

    tools = selected_tool_ids(query=query, project_root=tmp_path, force_code="RPF")

    assert tools[0] == "scout.ai.pace_guardian.assess.v0"
    assert tools.count("scout.ai.pace_guardian.assess.v0") == 1
    assert "scout.ai.energy_vitals.assess.v0" in tools


def test_nav_terrain_shape_uses_map_perception_as_primary_tool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        eval_module,
        "plan_scout_ai_tools",
        lambda *args, **kwargs: SimpleNamespace(selected_tools=[]),
    )
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="這個谷地有沒有自然出口，還是三面封閉？",
        project_id="demo",
    )

    tools = selected_tool_ids(query=query, project_root=tmp_path, force_code="NAV")

    assert tools[0] == "pydantic_ai.tool.search_scout_map_perception.v0"


def test_nav_weather_terrain_compound_uses_weather_as_primary_tool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        eval_module,
        "plan_scout_ai_tools",
        lambda *args, **kwargs: SimpleNamespace(selected_tools=[]),
    )
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="這段橫切坡在下雨後會增加哪些地形風險？",
        project_id="demo",
    )

    tools = selected_tool_ids(query=query, project_root=tmp_path, force_code="NAV")

    assert tools[0] == "scout.ai.weather_window.assess.v0"


def test_synthetic_spatial_search_is_anchored_to_current_snapshot(tmp_path: Path) -> None:
    arguments = _synthetic_field_context_arguments(
        question="哪一側具有較高的暴露或滑墜後果？",
        tool_id="pydantic_ai.tool.search_scout_map_perception.v0",
        project_root=tmp_path,
        live_navigation_snapshot={"lat": 24.05, "lon": 121.22},
    )

    assert arguments == {"lat": 24.05, "lon": 121.22, "radius_m": 1500.0}


def test_missing_evidence_distinguishes_primary_from_supplemental_gaps() -> None:
    blocking, supplemental = split_missing_evidence(
        force_code="WTH",
        missing_evidence=[
            "scout.ai.cwa_environment.assess.v0:missing:fresh_cwa_environment_evidence",
            "scout.ai.route_readiness.assess.v0:missing:team_members",
        ],
    )

    assert blocking == []
    assert len(supplemental) == 2

    blocking, supplemental = split_missing_evidence(
        force_code="WTH",
        missing_evidence=[
            "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence",
        ],
    )

    assert blocking == [
        "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence"
    ]
    assert supplemental == []


def test_nav_map_perception_gap_is_blocking_for_local_terrain_shape() -> None:
    blocking, supplemental = split_missing_evidence(
        force_code="NAV",
        question="哪一側具有較高的暴露或滑墜後果？",
        missing_evidence=[
            "pydantic_ai.tool.search_scout_map_perception.v0:missing:matching_map_perception_results",
            "scout.ai.navigation_terrain.assess.v0:missing:user_readiness",
        ],
    )

    assert blocking == [
        "pydantic_ai.tool.search_scout_map_perception.v0:missing:matching_map_perception_results"
    ]
    assert supplemental == [
        "scout.ai.navigation_terrain.assess.v0:missing:user_readiness"
    ]


def test_verifier_requires_blocking_evidence_gap_acknowledgement() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "NAV")
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "GO",
        "answer": "可以繼續前進。",
        "decisive_evidence": [],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": [],
        "source_refs": ["pydantic_ai.tool.search_scout_map_perception.v0"],
        "claims": ["candidate_only"],
    }
    gap = (
        "pydantic_ai.tool.search_scout_map_perception.v0:"
        "missing:matching_map_perception_results"
    )

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"pydantic_ai.tool.search_scout_map_perception.v0"},
        compact_evidence={
            "blocking_missing_evidence": [gap],
            "missing_evidence": [gap],
            "tools": [],
        },
    )

    assert "blocking_evidence_gap_not_acknowledged" in verified["errors"]
    assert "blocking_gap_requires_non_go_decision" in verified["errors"]


def test_question_specific_gap_does_not_require_generic_tool_tokens() -> None:
    generic_tool = {
        "tool_id": "scout.ai.route_context.assess.v0",
        "field_answer": "泛用景點摘要",
    }

    selected = quality_tool_results_for_gaps(
        tool_results=[generic_tool],
        blocking_missing_evidence=[
            "question_specific_route_context_evidence_missing"
        ],
    )

    assert selected == []


def test_any_blocking_gap_does_not_require_unrelated_primary_tool_tokens() -> None:
    selected = quality_tool_results_for_gaps(
        tool_results=[
            {
                "tool_id": "scout.ai.live_navigation_state.assess.v0",
                "field_answer": "地形導航判斷：建議 GO。",
            }
        ],
        blocking_missing_evidence=[
            "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence"
        ],
        question_id="NAV-077",
    )

    assert selected == []


def test_gap_aware_layered_answer_is_quality_needs_review() -> None:
    quality = assess_six_forces_answer_quality(
        (
            "天氣面可條件通行，但缺少預計目標 ETA 與日光窗口審查，"
            "無法完全確認回程安全。"
        ),
        missing_tools=[],
        blocking_missing_evidence=[
            "scout.ai.weather_window.assess.v0:missing:planned_target_eta"
        ],
        tool_results=[],
    )

    assert quality["classification"] == "quality_needs_review"
    assert quality["failure_reasons"] == ["missing_evidence_gap"]


def test_route_shape_uses_typed_verifier_instead_of_exact_field_copy() -> None:
    selected = quality_tool_results_for_gaps(
        tool_results=[
            {
                "tool_id": "scout.ai.route_architecture.assess.v0",
                "field_answer": "起終端點相距約 95.6 m，較符合 O 型或回到入口。",
            }
        ],
        blocking_missing_evidence=[],
        question_id="RTE-001",
    )

    assert selected == []


def test_source_ref_alias_is_resolved_only_by_unique_filename() -> None:
    output = {
        "source_refs": ["scout.ai.route_context_points.json"],
        "answer": "候選路線脈絡",
    }

    resolved = canonicalize_output_source_refs(
        output,
        {
            "candidates/route_context_points.json",
            "scout.ai.route_context.assess.v0",
        },
    )

    assert resolved["source_refs"] == ["candidates/route_context_points.json"]


def test_source_ref_missing_suffix_is_canonicalized_to_verified_tool() -> None:
    resolved = canonicalize_output_source_refs(
        {
            "source_refs": [
                "scout.ai.contextual_permission.assess.v0:missing:course_deg"
            ]
        },
        {"scout.ai.contextual_permission.assess.v0"},
    )

    assert resolved["source_refs"] == [
        "scout.ai.contextual_permission.assess.v0"
    ]
