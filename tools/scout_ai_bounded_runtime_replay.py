from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import assistant_pydantic_provider as provider_module  # noqa: E402
from assistant_pydantic_provider import PydanticAIEnvRunner  # noqa: E402
from pydantic_ai.messages import (  # noqa: E402
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402
from tools.scout_ai_live_tool_selection_eval import (  # noqa: E402
    load_eval_cases,
    run_live_tool_selection_eval,
    write_report,
)

DEFAULT_CASES_FILE = (
    ROOT / "outputs" / "evals" / "scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json"
)
DEFAULT_BEFORE_REPORT = (
    ROOT
    / "outputs"
    / "evals"
    / "free_model_100_20260713"
    / "north_mini_code"
    / "live_tool_selection_openrouter_cohere_north_mini_code_free_20260713T081619Z.json"
)
DEFAULT_WORKSPACE_ROOT = Path("/Users/alexwang0315/workspace")
DEFAULT_PROJECT_ID = "chilai_nanhua_day1_scoutAI"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "evals" / "bounded_context_progressive_disclosure"
DEFAULT_REPLAY_TIMEOUT_SECONDS = 90


class DeterministicProgressiveReplayRunner:
    """Exercise the real Pydantic tool protocol without claiming model quality."""

    model_name = "offline:deterministic-progressive-disclosure-replay"
    base_url = None
    evaluation_semantics = (
        "deterministic_disclosed_tool_protocol_not_model_quality"
    )
    calls_every_disclosed_tool = True

    def __init__(self) -> None:
        self._argument_generator = TestModel(seed=0)
        self._runner = PydanticAIEnvRunner(
            model_name=self.model_name,
            profile_name="local",
            workspace_tools_enabled=True,
            workspace_model_max_tokens=512,
        )

    def clone_for_isolated_run(self) -> "DeterministicProgressiveReplayRunner":
        """Return clean per-case state so a timeout cannot leak into another case."""

        return type(self)()

    @property
    def last_workspace_tool_invocations(self) -> list[dict[str, object]]:
        return self._runner.last_workspace_tool_invocations

    @property
    def last_model_usage(self) -> dict[str, int]:
        return self._runner.last_model_usage

    @property
    def last_model_response_metadata(self) -> dict[str, str]:
        return self._runner.last_model_response_metadata

    @property
    def last_agent_run_ledger(self) -> dict[str, Any]:
        return self._runner.last_agent_run_ledger

    @property
    def last_evidence_cards(self) -> list[dict[str, Any]]:
        return self._runner.last_evidence_cards

    @property
    def last_context_handles(self) -> list[dict[str, Any]]:
        return self._runner.last_context_handles

    @property
    def last_grounding_verification(self) -> dict[str, Any]:
        return self._runner.last_grounding_verification

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: object,
    ) -> str:
        original_factory = provider_module.build_chat_model
        provider_module.build_chat_model = lambda **_kwargs: FunctionModel(
            self._model_response,
            model_name=self.model_name,
        )
        try:
            return self._runner.run_with_workspace_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
        finally:
            provider_module.build_chat_model = original_factory

    def _model_response(
        self,
        messages: list[object],
        info: AgentInfo,
    ) -> ModelResponse:
        if info.function_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=tool.name,
                        args=self._argument_generator.gen_tool_args(tool),
                        tool_call_id=f"bounded_replay__{tool.name}",
                    )
                    for tool in info.function_tools
                ]
            )
        source_ref = _first_source_ref(_last_user_prompt(messages))
        if source_ref:
            excerpt = _first_evidence_excerpt(_last_user_prompt(messages))
            return ModelResponse(
                parts=[
                    TextPart(
                        "根據 Scout 候選證據，"
                        f"{excerpt or '已取得可引用的資料'} [{source_ref}]。"
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("目前缺少可引用的 Scout 證據。")])


def compare_eval_reports(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
) -> dict[str, Any]:
    before = _report_metrics(before_report)
    after = _report_metrics(after_report)
    before_input = int(before["input_tokens_per_turn"])
    after_input = int(after["input_tokens_per_turn"])
    reduction = (
        round((before_input - after_input) / before_input, 4)
        if before_input
        else None
    )
    return {
        "before": before,
        "after": after,
        "delta": {
            "input_tokens_per_turn_reduction_ratio": reduction,
            "request_count_per_turn": round(
                float(after["requests_per_turn"])
                - float(before["requests_per_turn"]),
                4,
            ),
            "tool_recall_micro": round(
                float(after["tool_recall_micro"])
                - float(before["tool_recall_micro"]),
                4,
            ),
            "exact_set_match_rate": round(
                float(after["exact_set_match_rate"])
                - float(before["exact_set_match_rate"]),
                4,
            ),
        },
    }


def _report_metrics(report: dict[str, Any]) -> dict[str, Any]:
    samples = report.get("samples")
    resolved_samples = samples if isinstance(samples, list) else []
    case_count = len(resolved_samples) or int(report.get("case_count") or 0)
    exact_count = 0
    total_required = 0
    total_found = 0
    input_per_case: list[int] = []
    selected_counts: list[int] = []
    executed_counts: list[int] = []
    grounded_count = 0
    unsupported_claim_count = 0
    for sample in resolved_samples:
        if not isinstance(sample, dict):
            continue
        required = _string_set(sample.get("required_tool_ids"))
        executed = _string_set(sample.get("model_native_tool_ids"))
        if required == executed:
            exact_count += 1
        total_required += len(required)
        total_found += len(required & executed)
        ledger = sample.get("agent_run_ledger")
        resolved_ledger = ledger if isinstance(ledger, dict) else {}
        usage = sample.get("model_usage")
        resolved_usage = usage if isinstance(usage, dict) else {}
        input_tokens = resolved_ledger.get("input_tokens", resolved_usage.get("input_tokens"))
        if isinstance(input_tokens, int):
            input_per_case.append(input_tokens)
        selected_counts.append(len(_string_set(resolved_ledger.get("selected_tool_ids"))))
        executed_counts.append(len(executed))
        grounding = sample.get("grounding_verification")
        if isinstance(grounding, dict):
            if grounding.get("passed") is True:
                grounded_count += 1
            unsupported = grounding.get("unsupported_claims")
            if isinstance(unsupported, list):
                unsupported_claim_count += len(unsupported)
    usage_totals = report.get("model_usage_totals")
    totals = usage_totals if isinstance(usage_totals, dict) else {}
    ledger_totals = report.get("agent_run_ledger_totals")
    overhead = ledger_totals if isinstance(ledger_totals, dict) else {}
    total_input = int(
        overhead.get("input_tokens")
        or totals.get("input_tokens")
        or sum(input_per_case)
    )
    total_requests = int(
        overhead.get("request_count") or totals.get("requests") or 0
    )
    return {
        "case_count": case_count,
        "input_tokens": total_input,
        "input_tokens_per_turn": round(total_input / case_count) if case_count else 0,
        "input_tokens_p95": _nearest_rank_percentile(input_per_case, 0.95),
        "requests": total_requests,
        "requests_per_turn": (
            round(total_requests / case_count, 4) if case_count else 0.0
        ),
        "tool_schema_chars": int(overhead.get("tool_schema_chars") or 0),
        "tool_result_chars": int(overhead.get("tool_result_chars") or 0),
        "selected_tools_per_turn": _mean(selected_counts),
        "executed_tools_per_turn": _mean(executed_counts),
        "tool_recall_micro": (
            round(total_found / total_required, 4) if total_required else 1.0
        ),
        "exact_set_match_count": exact_count,
        "exact_set_match_rate": (
            round(exact_count / case_count, 4) if case_count else 0.0
        ),
        "grounded_answer_count": grounded_count,
        "unsupported_claim_count": unsupported_claim_count,
    }


def _last_user_prompt(messages: list[object]) -> str:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


def _first_source_ref(prompt: str) -> str | None:
    _, separator, raw_payload = prompt.partition("\n")
    if not separator:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        match = re.search(r'"source_ref"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', prompt)
        if match is None:
            return None
        try:
            return str(json.loads(f'"{match.group(1)}"'))
        except json.JSONDecodeError:
            return match.group(1)

    def visit(value: object) -> str | None:
        if isinstance(value, dict):
            refs = value.get("source_refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, str) and ref.strip():
                        return ref.strip()
            for child in value.values():
                if found := visit(child):
                    return found
        elif isinstance(value, list):
            for child in value:
                if found := visit(child):
                    return found
        return None

    return visit(payload)


def _first_evidence_excerpt(prompt: str) -> str | None:
    _, separator, raw_payload = prompt.partition("\n")
    if not separator:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None

    def visit(value: object) -> str | None:
        if isinstance(value, dict):
            claim_summary = value.get("claim_summary")
            if isinstance(claim_summary, str) and claim_summary.strip():
                return claim_summary.strip()[:320]
            summary = value.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()[:320]
            snippets = value.get("snippets")
            if isinstance(snippets, list):
                for snippet in snippets:
                    if isinstance(snippet, str) and snippet.strip():
                        return snippet.strip()[:320]
            for child in value.values():
                if found := visit(child):
                    return found
        elif isinstance(value, list):
            for child in value:
                if found := visit(child):
                    return found
        return None

    return visit(payload)


def _nearest_rank_percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _mean(values: list[int]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", type=Path, default=DEFAULT_CASES_FILE)
    parser.add_argument("--before-report", type=Path, default=DEFAULT_BEFORE_REPORT)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_REPLAY_TIMEOUT_SECONDS,
    )
    args = parser.parse_args(argv)

    cases = load_eval_cases(args.cases_file)
    before_report = json.loads(args.before_report.read_text(encoding="utf-8"))
    runner = DeterministicProgressiveReplayRunner()
    after_report = run_live_tool_selection_eval(
        cases=cases,
        runner=runner,
        project_id=args.project_id,
        workspace_root=args.workspace_root,
        timeout_seconds=args.timeout_seconds,
        max_context_chars=2_000,
    )
    after_json, after_markdown = write_report(after_report, args.output_dir)
    comparison = compare_eval_reports(before_report, after_report)
    comparison_path = args.output_dir / "before_after_comparison.json"
    comparison_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_ai_bounded_runtime_replay_comparison",
                "replay_kind": "deterministic_pydantic_protocol_not_model_quality",
                "cases_file": args.cases_file.name,
                "before_report": args.before_report.name,
                "after_report": after_json.name,
                "comparison": comparison,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    comparison_path.chmod(0o600)
    print(
        json.dumps(
            {
                "status": "completed",
                "after_report": str(after_json),
                "after_markdown": str(after_markdown),
                "comparison": str(comparison_path),
                "metrics": comparison,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
