from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from scout.services.mser_runtime_adapter import MSERRuntimeAdapter
from tools import scout_ai_six_forces_openrouter_eval as eval_module


def test_normalizes_exact_openrouter_model_name() -> None:
    assert eval_module.normalize_openrouter_model("deepseek/deepseek-v4-flash") == (
        "openrouter:deepseek/deepseek-v4-flash"
    )
    assert (
        eval_module.normalize_openrouter_model("openrouter:deepseek/deepseek-v4-flash")
        == "openrouter:deepseek/deepseek-v4-flash"
    )


def test_normalizes_explicit_thinking_setting() -> None:
    assert eval_module.normalize_thinking_setting("default") is None
    assert eval_module.normalize_thinking_setting("off") is False
    assert eval_module.normalize_thinking_setting("minimal") == "minimal"


def test_builds_model_settings_with_recorded_thinking_control() -> None:
    assert eval_module.build_openrouter_model_settings(
        max_tokens=None,
        timeout_seconds=300,
        thinking=False,
    ) == {
        "temperature": 0,
        "thinking": False,
        "timeout": 300.0,
    }


def test_builds_explicit_cloud_model_adapter() -> None:
    def fake_model_call(**_kwargs):
        return "{}", {}

    adapter = eval_module.build_openrouter_model_adapter(fake_model_call)

    assert adapter.adapter_id == "openrouter.pydantic_ai"
    assert adapter.profile == "cloud"
    assert adapter.provider == "openrouter"
    assert adapter.transport == "pydantic_ai_openrouter"


def test_builds_cloud_adapter_with_contextual_native_tool_transport() -> None:
    def fake_model_call(**_kwargs):
        return "{}", {}

    def fake_contextual_call(**_kwargs):
        return "{}", {"native_tool_trace": {"tool_call_count": 1}}

    adapter = eval_module.build_openrouter_model_adapter(
        fake_model_call,
        contextual_model_call=fake_contextual_call,
    )

    assert adapter.invoke_with_context is fake_contextual_call


def test_redacts_openrouter_secret_from_error() -> None:
    message = eval_module.redact_provider_error(
        "Authorization: Bearer sk-or-v1-secret OPENROUTER_API_KEY=hidden",
        secrets=("sk-or-v1-secret", "hidden"),
    )

    assert "sk-or-v1-secret" not in message
    assert "hidden" not in message
    assert "[REDACTED]" in message


def test_requires_pydantic_ai_214(monkeypatch) -> None:
    monkeypatch.setattr(
        eval_module,
        "runtime_package_versions",
        lambda: {"pydantic_ai_slim": "2.12.4"},
    )

    with pytest.raises(RuntimeError, match="requires pydantic-ai-slim 2.14.x"):
        eval_module.require_pydantic_ai_214()


def test_openrouter_caller_executes_every_supplied_evidence_card_as_native_tools(
    monkeypatch,
) -> None:
    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        has_tool_return = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in getattr(message, "parts", ())
        )
        if not has_tool_return:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name=tool.name, args={})
                    for tool in info.function_tools
                ]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    '{"s":"scenario.1","d":null,"a":"工具證據已讀取",'
                    '"e":"兩張 evidence cards","o":"","g":"","c":"",'
                    '"r":["tool.one","tool.two"],"cl":"candidate_only"}'
                )
            ]
        )

    monkeypatch.setattr(
        eval_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    caller = eval_module.OpenRouterModelCaller(
        model_name="deepseek/deepseek-v4-flash",
        api_key="fixture-key",
        max_tokens=None,
        thinking=None,
    )

    raw, metadata = caller.call_with_context(
        endpoint=eval_module.OPENROUTER_ENDPOINT,
        model="openrouter:deepseek/deepseek-v4-flash",
        prompt="Use every relevant evidence tool, then answer.",
        timeout_seconds=30,
        structured_json=True,
        evidence_cards=[
            {"tool_id": "tool.one", "status": "completed", "field_answer": "A"},
            {"tool_id": "tool.two", "status": "completed", "field_answer": "B"},
        ],
        selected_tool_ids=["tool.one", "tool.two"],
    )

    assert "工具證據已讀取" in raw
    trace = metadata["native_tool_trace"]
    assert trace["tool_call_count"] == 2
    assert trace["tool_return_count"] == 2
    assert trace["called_tool_ids"] == ["tool.one", "tool.two"]
    assert metadata["usage"]["tool_calls"] == 2


def test_run_eval_records_openrouter_manifest_and_scenario_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    scenario_path = workspace / "outputs" / "evals" / "scenario.json"
    scenario_path.parent.mkdir(parents=True)
    scenario_path.write_text(
        json.dumps({"project_id": "demo", "scenarios": [], "cases": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_module, "expand_case_runs", lambda _artifact: [])
    monkeypatch.setattr(
        eval_module,
        "require_pydantic_ai_214",
        lambda: (_ for _ in ()).throw(
            AssertionError("no provider gate is needed when no model call is pending")
        ),
    )
    args = SimpleNamespace(
        workspace=workspace,
        scenario_artifact=Path("outputs/evals/scenario.json"),
        model="deepseek/deepseek-v4-flash",
        api_key="secret",
        timeout_seconds=0,
        model_max_tokens=None,
        thinking="default",
        max_model_requests=10,
        guided_retry=True,
        max_runs=None,
        offset=0,
        question_id=[],
        run_id="test-run",
        resume=False,
        revalidate_existing=False,
        workers=4,
    )

    run_dir = eval_module.run_eval(args)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert manifest["model"] == "openrouter:deepseek/deepseek-v4-flash"
    assert manifest["model_adapter_id"] == "openrouter.pydantic_ai"
    assert manifest["model_profile"] == "cloud"
    assert manifest["provider"] == "openrouter"
    assert manifest["model_transport"] == "pydantic_ai_openrouter"
    assert manifest["base_question_count"] == 0
    assert manifest["model_run_count"] == 0
    assert manifest["workers"] == 4
    assert manifest["thinking"] is None
    assert manifest["model_external_api_calls_made"] is False
    assert manifest["weather_external_api_calls_made"] is False
    assert manifest["candidate_only"] is True
    assert manifest["runtime_safety_truth"] is False
    assert manifest["cloud_evidence_transport"] == "pydantic_native_tools_full_cards"
    assert manifest["cloud_prompt_character_limit"] is None
    assert manifest["native_tool_calls_required"] is True
    assert (run_dir / "scenario_artifact.snapshot.json").exists()
    assert "secret" not in (run_dir / "run_manifest.json").read_text(encoding="utf-8")


def test_resume_preserves_original_start_time_and_records_resume_time(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    scenario_path = workspace / "outputs" / "evals" / "scenario.json"
    scenario_path.parent.mkdir(parents=True)
    scenario_path.write_text(
        json.dumps({"project_id": "demo", "scenarios": [], "cases": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_module, "expand_case_runs", lambda _artifact: [])
    timestamps = iter(("2026-07-21T01:00:00+00:00", "2026-07-21T02:00:00+00:00"))
    monkeypatch.setattr(eval_module, "utc_iso", lambda: next(timestamps))
    args = SimpleNamespace(
        workspace=workspace,
        scenario_artifact=Path("outputs/evals/scenario.json"),
        model="deepseek/deepseek-v4-flash",
        api_key="secret",
        timeout_seconds=0,
        model_max_tokens=None,
        thinking="off",
        max_model_requests=10,
        guided_retry=True,
        max_runs=None,
        offset=0,
        question_id=[],
        run_id="resume-run",
        resume=False,
        revalidate_existing=False,
        workers=1,
    )

    run_dir = eval_module.run_eval(args)
    args.resume = True
    eval_module.run_eval(args)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert manifest["started_at"] == "2026-07-21T01:00:00+00:00"
    assert manifest["resumed_at"] == "2026-07-21T02:00:00+00:00"


def test_resume_retries_failed_run_and_uses_latest_passing_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "per_case_results.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_case_id": "case-1",
                        "verifier": {"status": "fail"},
                        "context_identity_check": {"status": "pass"},
                    }
                ),
                json.dumps(
                    {
                        "run_case_id": "case-2",
                        "verifier": {"status": "pass"},
                        "context_identity_check": {"status": "pass"},
                    }
                ),
                json.dumps(
                    {
                        "run_case_id": "case-2",
                        "verifier": {"status": "pass"},
                        "context_identity_check": {"status": "pass"},
                        "attempt": "latest",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    existing, completed = eval_module._load_existing_results(path)

    assert completed == {"case-2"}
    assert len(existing) == 1
    assert existing[0]["attempt"] == "latest"


def test_mser_revalidation_integrity_report_proves_model_payload_is_preserved(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "per_case_results.jsonl"
    output_path = tmp_path / "mser_revalidation_integrity.json"
    provider_row = {
        "run_case_id": "case-1",
        "model_output": {"answer": "provider answer"},
        "raw_model_output": "raw provider answer",
        "model_metadata": {"provider": "openrouter"},
        "model_request_count": 1,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    shadow_row = {
        **provider_row,
        "mser_mode": "shadow",
        "mser_error": None,
        "revalidation": {"model_call_performed": False},
    }
    results_path.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False) for item in (provider_row, shadow_row)
        )
        + "\n",
        encoding="utf-8",
    )

    report = eval_module._write_mser_revalidation_integrity_report(
        results_path=results_path,
        output_path=output_path,
    )

    assert report["latest_run_count"] == 1
    assert report["compared_run_count"] == 1
    assert report["preserved_model_payload_count"] == 1
    assert report["mismatched_run_case_ids"] == []
    assert report["model_call_performed_count"] == 0
    assert report["mser_mode_counts"] == {"shadow": 1}
    assert json.loads(output_path.read_text(encoding="utf-8")) == report


def test_revalidate_existing_result_preserves_model_output_without_new_call() -> None:
    gap = "scout.ai.weather_window.assess.v0:missing:fresh_route_weather_evidence"
    run = {
        "scenario_id": "scenario-1",
        "question_id": "WTH-001",
        "force_code": "WTH",
        "variant_id": "stale_unknown_weather",
        "condition_overlay": {"variant_id": "stale_unknown_weather"},
        "expected_decisions": ["DELAY"],
        "expected_decision_boundary": {"answer_mode": "decision"},
    }
    output = {
        "scenario_id": "scenario-1",
        "decision": "DELAY",
        "answer": "天氣資料過期且未知，需取得新鮮證據後再判斷。",
        "decisive_evidence": [],
        "opposing_evidence": [],
        "evidence_gaps": [gap],
        "decision_change_conditions": ["取得新鮮天氣證據"],
        "source_refs": ["scout.ai.weather_window.assess.v0"],
        "claims": ["candidate_only"],
    }
    row = {
        "question_id": "WTH-001",
        "run_case_id": "case-1",
        "model_output": output,
        "raw_model_output": "preserved raw output",
        "source_refs": ["scout.ai.weather_window.assess.v0"],
        "completed_tools": ["scout.ai.weather_window.assess.v0"],
        "missing_tools": [],
        "blocking_missing_evidence": [gap],
        "tool_evidence_stage": [
            {
                "tool_id": "scout.ai.weather_window.assess.v0",
                "field_answer": "天氣資料過期且未知。",
            }
        ],
        "compact_evidence_stage": {
            "blocking_missing_evidence": [gap],
            "missing_evidence": [gap],
            "tools": [],
        },
        "context_identity_check": {"status": "pass"},
        "native_tool_call_required": True,
        "model_metadata": {
            "native_tool_trace": {
                "offered_tool_ids": ["scout.ai.weather_window.assess.v0"],
                "called_tool_ids": ["scout.ai.weather_window.assess.v0"],
                "tool_call_count": 1,
                "tool_return_count": 1,
            }
        },
        "verifier": {"status": "pass"},
        "answer_quality_screen": {"classification": "quality_fail"},
        "failure_category": "missing_evidence",
    }

    result = eval_module.revalidate_existing_result(row, run=run)

    assert result["model_output"] == output
    assert result["raw_model_output"] == "preserved raw output"
    assert result["verifier"]["status"] == "pass"
    assert result["answer_quality_screen"]["classification"] == "quality_needs_review"
    assert result["three_axis_scorecard"]["transport_schema"]["score"] == 100
    assert result["three_axis_scorecard"]["semantic_answer_quality"]["score"] == 100
    assert result["revalidation"]["model_call_performed"] is False


def test_revalidate_existing_result_adds_mser_shadow_trace_without_model_call() -> None:
    source_ref = "outputs/weather/route_weather_package.json"
    weather_tool_id = "scout.ai.weather_window.assess.v0"
    run = {
        "scenario_id": "scenario-1",
        "question_id": "WTH-002",
        "question_text": "哪些地方下雨後會變危險？",
        "force_code": "WTH",
        "variant_id": "rain",
        "condition_overlay": {"variant_id": "rain"},
        "expected_decisions": ["REVIEW"],
        "expected_decision_boundary": {"answer_mode": "decision"},
        "scenario": {
            "scenario_id": "scenario-1",
            "observed_at": "2026-07-24T01:30:00+00:00",
        },
    }
    output = {
        "scenario_id": "scenario-1",
        "decision": "REVIEW",
        "answer": "雨後應優先檢查高風險坡段。",
        "decisive_evidence": [source_ref],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": ["取得更新的降雨證據"],
        "source_refs": [source_ref],
        "claims": ["candidate_only"],
    }
    row = {
        "question_id": "WTH-002",
        "run_case_id": "case-2",
        "question": run["question_text"],
        "model_output": output,
        "raw_model_output": "preserved raw output",
        "source_refs": [source_ref],
        "completed_tools": [weather_tool_id],
        "selected_tools": [weather_tool_id],
        "missing_tools": [],
        "blocking_missing_evidence": [],
        "tool_evidence_stage": [
            {
                "tool_id": weather_tool_id,
                "status": "completed",
                "quality": "verified",
                "source_refs": [source_ref],
                "weather_trend": "deteriorating",
                "danger_window": "within_3_hours",
            }
        ],
        "compact_evidence_stage": {
            "blocking_missing_evidence": [],
            "missing_evidence": [],
            "tools": [],
        },
        "context_identity_check": {"status": "pass"},
        "native_tool_call_required": True,
        "model_metadata": {
            "native_tool_trace": {
                "offered_tool_ids": [weather_tool_id],
                "called_tool_ids": [weather_tool_id],
                "tool_call_count": 1,
                "tool_return_count": 1,
            }
        },
        "verifier": {"status": "pass"},
        "answer_quality_screen": {"classification": "quality_pass"},
        "failure_category": None,
    }

    result = eval_module.revalidate_existing_result(
        row,
        run=run,
        mser_mode="shadow",
        mser_runtime_adapter=MSERRuntimeAdapter(),
    )

    assert result["model_output"] == output
    assert result["mser_mode"] == "shadow"
    assert result["mser_error"] is None
    assert result["mser_trace"]["candidate_only"] is True
    assert result["mser_trace"]["runtime_safety_truth"] is False
    assert result["mser_trace"]["initial"]["decision"]["type"] == "weather"
    assert result["mser_answer_verification"]["passed"] is False
    assert result["mser_answer_verification"]["violations"][0]["code"] == (
        "reasoning_not_allowed"
    )
    assert result["revalidation"]["model_call_performed"] is False

    enforced = eval_module.revalidate_existing_result(
        row,
        run=run,
        mser_mode="enforce",
        mser_runtime_adapter=MSERRuntimeAdapter(),
    )

    assert enforced["model_output"] == output
    assert enforced["verifier"]["status"] == "fail"
    assert "mser_reasoning_blocked:evidence_gap" in enforced["verifier"]["errors"]
    assert enforced["revalidation"]["model_call_performed"] is False
