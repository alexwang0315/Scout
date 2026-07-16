from __future__ import annotations

from pathlib import Path

import tools.scout_ai_live_tool_selection_eval as live_eval_module
from tools.scout_ai_live_tool_selection_eval import (
    EvalCase,
    _context_tool_ids,
    _format_markdown,
    run_live_tool_selection_eval,
    write_report,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"


class FakeNoToolRunner:
    model_name = "fake/no-tool"
    base_url = None
    last_workspace_tool_invocations = []
    last_model_usage = {
        "requests": 1,
        "tool_calls": 0,
        "input_tokens": 120,
        "output_tokens": 24,
    }
    last_model_response_metadata = {
        "finish_reason": "stop",
        "model_name": "fake/no-tool",
        "provider": "hailo_ollama",
        "streaming": "true",
        "semantic_stop": "true",
        "input_pack_estimated_tokens": "1180",
        "continuation_count": "1",
        "context_full_recovery_count": "1",
    }

    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        return "I answered without calling tools."


class FakeWeatherToolRunner:
    model_name = "fake/weather-tools"
    base_url = None
    last_workspace_tool_invocations = []
    last_agent_run_ledger = {
        "request_count": 2,
        "tool_call_count": 2,
        "system_chars": 800,
        "tool_schema_count": 2,
        "tool_schema_chars": 1400,
        "user_history_chars": 600,
        "tool_result_chars": 900,
        "input_tokens": 1300,
        "cache_write_tokens": 0,
        "cache_read_tokens": 200,
        "output_tokens": 180,
        "estimated_cost": 0.001,
        "budget_remaining": {"input_tokens": 18700},
        "budget_stop_reason": None,
        "selected_tool_ids": [
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ],
        "executed_tool_ids": [
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ],
        "retry_count": 0,
        "repair_count": 0,
        "requests": [],
    }
    last_context_handles = [
        {
            "context_id": "scout.context.weather_window",
            "scope_metadata": {
                "tool_ids": ["scout.ai.weather_window.assess.v0"]
            },
        }
    ]
    last_grounding_verification = {
        "passed": True,
        "output_disposition": "grounded",
        "cited_source_refs": [],
        "invalid_source_refs": [],
        "unsupported_claims": [],
        "rejected_draft_claims": [],
        "repair_items": [],
    }

    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        tool_context.search_scout_weather_window(
            query="白牆下這段還適合走嗎？",
            limit=2,
        )
        tool_context.search_scout_cwa_environment(
            query="白牆下這段還適合走嗎？",
            limit=2,
        )
        self.last_workspace_tool_invocations = list(tool_context.invocations)
        return "I used weather and CWA evidence."


class FakeFailClosedRunner(FakeWeatherToolRunner):
    last_grounding_verification = {
        "passed": False,
        "output_disposition": "fail_closed",
        "cited_source_refs": [],
        "invalid_source_refs": [],
        "unsupported_claims": [],
        "rejected_draft_claims": ["The route has 999 checkpoints."],
        "repair_items": ["fail_closed_no_grounded_answer"],
    }

    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        super().run_with_workspace_tools(
            prompt,
            timeout_seconds=timeout_seconds,
            tool_context=tool_context,
        )
        return "目前無法從已驗證的 Scout 證據產生可靠答案。"


class FakeFailedToolRunner(FakeWeatherToolRunner):
    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        super().run_with_workspace_tools(
            prompt,
            timeout_seconds=timeout_seconds,
            tool_context=tool_context,
        )
        tool_context.invocations[0]["status"] = "failed"
        self.last_workspace_tool_invocations = list(tool_context.invocations)
        return "The required tool failed."


class FakeSuccessStatusToolRunner(FakeWeatherToolRunner):
    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        output = super().run_with_workspace_tools(
            prompt,
            timeout_seconds=timeout_seconds,
            tool_context=tool_context,
        )
        tool_context.invocations[1]["status"] = "success"
        self.last_workspace_tool_invocations = list(tool_context.invocations)
        return output


class FakeProviderErrorAfterDraftRunner(FakeWeatherToolRunner):
    last_grounding_verification = {
        "passed": False,
        "output_disposition": "needs_repair",
        "cited_source_refs": [],
        "invalid_source_refs": [],
        "unsupported_claims": ["Rejected draft claim."],
        "rejected_draft_claims": ["Rejected draft claim."],
        "repair_items": ["unsupported_claim:Rejected draft claim."],
    }

    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        super().run_with_workspace_tools(
            prompt,
            timeout_seconds=timeout_seconds,
            tool_context=tool_context,
        )
        raise RuntimeError("provider stopped after draft verification")


def test_live_eval_counts_only_model_native_tool_calls() -> None:
    case = EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=FakeNoToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    assert report["failed_count"] == 1
    assert report["samples"][0]["model_native_tool_call_count"] == 0
    assert report["samples"][0]["required_tools_matched"] is False
    assert report["scoring_policy"]["assistant_api_pre_augmentation_used"] is False


def test_live_eval_preserves_full_answer_and_aggregates_model_usage() -> None:
    long_answer = "完整答案" * 200

    class FakeUsageRunner(FakeNoToolRunner):
        last_raw_model_output = "raw model draft"
        last_raw_model_outputs = ["raw model draft", "raw repaired draft"]

        def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
            return long_answer

    report = run_live_tool_selection_eval(
        cases=(EvalCase("workspace-001", "workspace 有什麼？", ()),),
        runner=FakeUsageRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["answer"] == long_answer
    assert sample["raw_model_answer"] == "raw model draft"
    assert sample["raw_model_attempts"] == [
        "raw model draft",
        "raw repaired draft",
    ]
    assert len(sample["answer_preview"]) < len(sample["answer"])
    assert sample["model_usage"]["input_tokens"] == 120
    assert sample["model_response_metadata"]["finish_reason"] == "stop"
    assert sample["model_response_metadata"]["provider"] == "hailo_ollama"
    assert sample["model_response_metadata"]["streaming"] == "true"
    assert sample["model_response_metadata"]["semantic_stop"] == "true"
    assert sample["model_response_metadata"]["input_pack_estimated_tokens"] == "1180"
    assert sample["model_response_metadata"]["continuation_count"] == "1"
    assert sample["model_response_metadata"]["context_full_recovery_count"] == "1"
    assert sample["answer_completed"] is True
    assert report["answer_completed_count"] == 1
    assert report["answer_completion_rate"] == 1.0
    assert report["model_usage_totals"] == {
        "requests": 1,
        "tool_calls": 0,
        "input_tokens": 120,
        "output_tokens": 24,
    }


def test_live_eval_does_not_count_length_terminated_answer_as_complete() -> None:
    class FakeLengthRunner(FakeNoToolRunner):
        last_model_response_metadata = {
            "finish_reason": "length",
            "model_name": "fake/length",
        }

    report = run_live_tool_selection_eval(
        cases=(EvalCase("workspace-001", "workspace 有什麼？", ()),),
        runner=FakeLengthRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    assert report["samples"][0]["answer_completed"] is False
    assert report["answer_completed_count"] == 0
    assert report["answer_completion_rate"] == 0.0


def test_live_eval_passes_when_model_calls_required_tools() -> None:
    case = EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=FakeWeatherToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert report["passed_count"] == 1
    assert sample["required_tools_matched"] is True
    assert sample["model_native_tool_ids"] == [
        "scout.ai.weather_window.assess.v0",
        "scout.ai.cwa_environment.assess.v0",
    ]
    assert sample["tool_recall"] == 1.0
    assert sample["exact_required_tool_set_match"] is True
    assert sample["agent_run_ledger"]["tool_schema_chars"] == 1400
    assert report["exact_set_match_count"] == 1
    assert report["tool_recall_micro"] == 1.0
    assert report["agent_run_ledger_totals"]["tool_result_chars"] == 900
    assert sample["context_top3_hit"] is True
    assert report["context_top3_recall"] == 1.0
    assert report["context_top3_macro_recall"] == 1.0
    assert report["context_top3_exact_match_rate"] == 1.0


def test_live_eval_context_top3_reports_true_micro_recall_not_any_hit(
    monkeypatch,
) -> None:
    required = (
        "scout.ai.weather_window.assess.v0",
        "scout.ai.cwa_environment.assess.v0",
    )
    monkeypatch.setattr(
        live_eval_module,
        "_context_tool_ids",
        lambda _project_root: frozenset(required),
    )

    report = run_live_tool_selection_eval(
        cases=(EvalCase("field-031", "白牆下這段還適合走嗎？", required),),
        runner=FakeWeatherToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    assert report["context_top3_any_hit_rate"] == 1.0
    assert report["context_top3_recall"] == 0.5
    assert report["context_top3_macro_recall"] == 0.5
    assert report["context_top3_exact_match_rate"] == 0.0


def test_context_metric_oracle_excludes_domains_not_disclosed_to_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class Source:
        def __init__(self, domain: str, tool_ids: list[str]) -> None:
            self.domain = domain
            self.tool_ids = tool_ids

    class Registry:
        sources = [
            Source("route", ["route.tool"]),
            Source("health", ["health.tool"]),
            Source("team", ["team.tool"]),
        ]

    monkeypatch.setattr(
        live_eval_module,
        "discover_scout_ai_context_sources",
        lambda *_args, **_kwargs: Registry(),
    )
    _context_tool_ids.cache_clear()

    assert _context_tool_ids(tmp_path / "unique-project") == frozenset(
        {"route.tool"}
    )


def test_live_eval_does_not_pass_failed_required_tool_execution() -> None:
    case = EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=FakeFailedToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["required_tools_selected"] is True
    assert sample["required_tools_matched"] is False
    assert sample["failure_category"] == "tool_status_error"
    assert report["passed_count"] == 0
    assert report["pass_rate"] == 0.0


def test_live_eval_accepts_typed_workspace_query_success_status() -> None:
    case = EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=FakeSuccessStatusToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["required_tools_matched"] is True
    assert sample["failure_category"] == "ok"
    assert report["passed_count"] == 1


def test_live_eval_does_not_count_fail_closed_text_as_answer_or_unsupported_claim() -> None:
    case = EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
        ),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=FakeFailClosedRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["answer_completed"] is False
    assert sample["answer_grounded"] is False
    assert sample["failure_category"] == "answer_fail_closed"
    assert sample["grounding_verification"]["unsupported_claims"] == []


def test_live_eval_separates_rejected_drafts_from_user_visible_claims() -> None:
    report = run_live_tool_selection_eval(
        cases=(
            EvalCase(
                "field-031",
                "白牆下這段還適合走嗎？",
                (
                    "scout.ai.weather_window.assess.v0",
                    "scout.ai.cwa_environment.assess.v0",
                ),
            ),
        ),
        runner=FakeProviderErrorAfterDraftRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["answer"] == ""
    assert sample["grounding_verification"]["unsupported_claims"] == []
    assert sample["grounding_verification"]["unsupported_claim_count"] == 1
    assert sample["user_visible_unsupported_claims"] == []
    assert "rejected_draft_claims" not in sample["grounding_verification"]
    assert sample["grounding_verification"]["rejected_draft_claim_count"] == 1
    assert report["user_visible_unsupported_claim_count"] == 0


def test_live_eval_markdown_reports_bounded_runtime_quality_and_failure_metrics() -> None:
    report = run_live_tool_selection_eval(
        cases=(
            EvalCase(
                "field-031",
                "白牆下這段還適合走嗎？",
                (
                    "scout.ai.weather_window.assess.v0",
                    "scout.ai.cwa_environment.assess.v0",
                ),
            ),
        ),
        runner=FakeWeatherToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    markdown = _format_markdown(report)

    assert "tool_recall_micro" in markdown
    assert "exact_set_match_rate" in markdown
    assert "context_top3_recall" in markdown
    assert "agent_run_ledger_totals" in markdown
    assert "failure_category_counts" in markdown
    assert "Failure category" in markdown
    assert "Grounded" in markdown


def test_live_eval_distinguishes_required_recall_from_exact_set_match() -> None:
    class FakeExtraToolRunner(FakeWeatherToolRunner):
        last_agent_run_ledger = {
            **FakeWeatherToolRunner.last_agent_run_ledger,
            "selected_tool_ids": [
                "scout.ai.weather_window.assess.v0",
                "scout.ai.cwa_environment.assess.v0",
                "pydantic_ai.tool.search_scout_route_structure.v0",
            ],
        }

        def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
            super().run_with_workspace_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
            tool_context.search_scout_route_structure(query="route", limit=1)
            return "I used required evidence plus an extra tool."

    report = run_live_tool_selection_eval(
        cases=(
            EvalCase(
                "field-031",
                "白牆下這段還適合走嗎？",
                (
                    "scout.ai.weather_window.assess.v0",
                    "scout.ai.cwa_environment.assess.v0",
                ),
            ),
        ),
        runner=FakeExtraToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["required_tools_selected"] is True
    assert sample["exact_required_tool_set_match"] is False
    assert sample["extra_native_tool_ids"] == [
        "pydantic_ai.tool.search_scout_route_structure.v0"
    ]
    assert sample["failure_category"] == "extra_tools_exact_miss"
    assert report["exact_set_match_count"] == 0


def test_live_eval_does_not_count_duplicate_required_calls_as_exact() -> None:
    class FakeDuplicateToolRunner(FakeWeatherToolRunner):
        def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
            super().run_with_workspace_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
            tool_context.search_scout_weather_window(query="duplicate", limit=1)
            self.last_workspace_tool_invocations = list(tool_context.invocations)
            return "I called one required tool twice."

    report = run_live_tool_selection_eval(
        cases=(
            EvalCase(
                "field-031",
                "白牆下這段還適合走嗎？",
                (
                    "scout.ai.weather_window.assess.v0",
                    "scout.ai.cwa_environment.assess.v0",
                ),
            ),
        ),
        runner=FakeDuplicateToolRunner(),
        workspace_root=WORKSPACE_ROOT,
    )

    sample = report["samples"][0]
    assert sample["required_tools_selected"] is True
    assert sample["exact_required_tool_set_match"] is False
    assert sample["extra_native_tool_ids"] == [
        "scout.ai.weather_window.assess.v0"
    ]


def test_live_eval_uses_isolated_runner_clone_per_case() -> None:
    class CloneableRunner(FakeNoToolRunner):
        def __init__(self, *, isolated: bool = False) -> None:
            self.isolated = isolated
            self.clones: list[CloneableRunner] = []
            self.call_count = 0

        def clone_for_isolated_run(self):
            clone = CloneableRunner(isolated=True)
            self.clones.append(clone)
            return clone

        def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
            assert self.isolated, "the shared runner must not execute an eval case"
            self.call_count += 1
            return "isolated answer"

    runner = CloneableRunner()
    run_live_tool_selection_eval(
        cases=(
            EvalCase("workspace-001", "workspace 有什麼？", ()),
            EvalCase("workspace-002", "route 有什麼？", ()),
        ),
        runner=runner,
        workspace_root=WORKSPACE_ROOT,
    )

    assert len(runner.clones) == 2
    assert [clone.call_count for clone in runner.clones] == [1, 1]


def test_live_eval_report_redacts_endpoint_and_uses_private_file_mode(
    tmp_path: Path,
) -> None:
    class CredentialedRunner(FakeNoToolRunner):
        base_url = "https://user:password@example.test/v1?token=must-not-appear"

    report = run_live_tool_selection_eval(
        cases=(EvalCase("workspace-001", "workspace 有什麼？", ()),),
        runner=CredentialedRunner(),
        workspace_root=WORKSPACE_ROOT,
    )
    json_path, markdown_path = write_report(report, tmp_path)

    assert report["workspace_root"] == WORKSPACE_ROOT.name
    assert report["base_url"] is None
    assert report["artifact_sensitivity"] == "sensitive_local_eval"
    assert json_path.stat().st_mode & 0o777 == 0o600
    assert markdown_path.stat().st_mode & 0o777 == 0o600
    assert "must-not-appear" not in json_path.read_text(encoding="utf-8")


def test_live_eval_paces_between_cases_without_delaying_after_last(monkeypatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(live_eval_module.time, "sleep", delays.append)
    cases = (
        EvalCase("workspace-001", "workspace 有什麼？", ()),
        EvalCase("workspace-002", "route 有什麼？", ()),
    )

    report = run_live_tool_selection_eval(
        cases=cases,
        runner=FakeNoToolRunner(),
        workspace_root=WORKSPACE_ROOT,
        delay_between_cases_seconds=4.5,
    )

    assert delays == [4.5]
    assert report["pacing"]["delay_between_cases_seconds"] == 4.5
