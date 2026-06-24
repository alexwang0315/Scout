from __future__ import annotations

from pathlib import Path

from tools.scout_ai_live_tool_selection_eval import (
    EvalCase,
    run_live_tool_selection_eval,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"


class FakeNoToolRunner:
    model_name = "fake/no-tool"
    base_url = None
    last_workspace_tool_invocations = []

    def run_with_workspace_tools(self, prompt, *, timeout_seconds, tool_context):
        return "I answered without calling tools."


class FakeWeatherToolRunner:
    model_name = "fake/weather-tools"
    base_url = None
    last_workspace_tool_invocations = []

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
