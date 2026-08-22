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
from scout.schemas.agent_runtime import (  # noqa: E402
    AgentRequestLedger,
    AgentRunLedger,
    QuestionClass,
)
from scout.services.agent_budget_policy import AgentBudgetPolicy  # noqa: E402
from scout.services.bounded_agent_runtime import BoundedAgentRuntime  # noqa: E402
from scout.services.workspace_query import WorkspaceQueryService  # noqa: E402
from scout_workspace_query_tool import WORKSPACE_QUERY_TOOL_ID  # noqa: E402
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
DEFAULT_REPLAY_TIMEOUT_SECONDS = 0
DEFAULT_REPLAY_MAX_CONTEXT_CHARS: int | None = None


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
            workspace_model_max_tokens=None,
        )
        # Constructor env fallbacks are useful in production, but this replay is
        # explicitly unbounded by Scout in Aggressive Construction Mode.
        self._runner.workspace_model_max_tokens = None

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

    @property
    def last_agent_recovery(self) -> dict[str, Any]:
        return self._runner.last_agent_recovery

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
            prompt = _last_user_prompt(messages)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=tool.name,
                        args=_deterministic_tool_args(
                            tool,
                            prompt=prompt,
                            fallback=self._argument_generator.gen_tool_args(tool),
                        ),
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


def run_workspace_15k_join_replay(project_root: Path) -> dict[str, Any]:
    """Replay a 10-step mileage-anchor-to-checkpoint evidence trajectory."""

    project_root = project_root.expanduser().resolve(strict=True)
    service = WorkspaceQueryService(project_root)
    budget = AgentBudgetPolicy.for_query(
        question_class=QuestionClass.CROSS_ARTIFACT_JOIN,
        selected_tool_ids=[WORKSPACE_QUERY_TOOL_ID],
        expected_operations=[
            "inspect",
            "filter",
            "count",
            "nearest",
            "freshness",
        ],
        requires_join=True,
    )
    runtime = BoundedAgentRuntime(budget=budget)
    call_trace: list[dict[str, Any]] = []
    evidence_cards = []

    def execute(stage: str, request: dict[str, Any]):
        if len(call_trace) >= budget.max_tool_calls:
            raise RuntimeError("15K replay attempted to exceed its stage tool budget")
        response = service.execute(request)
        serialized = response.model_dump(mode="json")
        call_trace.append(
            {
                "index": len(call_trace) + 1,
                "stage": stage,
                "operation": str(response.operation),
                "status": response.status,
                "answerability": response.answerability,
                "source_refs": response.source_refs,
                "request": request,
                "response": serialized,
            }
        )
        if response.status == "error":
            raise RuntimeError(
                f"15K replay query failed at {stage}: {response.root_cause}"
            )
        evidence_cards.append(
            runtime.evidence_from_tool_result(
                WORKSPACE_QUERY_TOOL_ID,
                serialized,
            )
        )
        return response

    manifest = execute(
        "search",
        {
            "operation": "inspect",
            "artifact": {"source_ref": "project.json"},
            "fields": [
                "route_mileage_k_anchors_ref",
                "checkpoint_candidates_ref",
            ],
        },
    )
    anchor_inspect = execute(
        "drilldown",
        {
            "operation": "inspect",
            "artifact": {"project_ref_key": "route_mileage_k_anchors_ref"},
            "fields": [
                "candidate_id",
                "display_label",
                "mileage_m",
                "lat",
                "lon",
            ],
        },
    )
    anchor_filter = execute(
        "filter",
        {
            "operation": "filter",
            "artifact": {"project_ref_key": "route_mileage_k_anchors_ref"},
            "predicates": [
                {"field": "display_label", "operator": "eq", "value": "15K"}
            ],
            "fields": [
                "candidate_id",
                "display_label",
                "mileage_m",
                "lat",
                "lon",
            ],
            "limit": 10,
        },
    )
    anchor_count = execute(
        "aggregation",
        {
            "operation": "count",
            "artifact": {"project_ref_key": "route_mileage_k_anchors_ref"},
            "predicates": [
                {"field": "display_label", "operator": "eq", "value": "15K"}
            ],
        },
    )
    checkpoint_inspect = execute(
        "drilldown",
        {
            "operation": "inspect",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "fields": ["candidate_id", "label", "lat", "lon"],
        },
    )

    if anchor_filter.result_count != 1 or not anchor_filter.results:
        raise RuntimeError("15K replay requires exactly one 15K mileage anchor")
    anchor = anchor_filter.results[0].data
    lat = _required_float(anchor, "lat")
    lon = _required_float(anchor, "lon")
    nearest = execute(
        "join",
        {
            "operation": "nearest",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "origin": {"lat": lat, "lon": lon},
            "lat_field": "lat",
            "lon_field": "lon",
            "fields": ["candidate_id", "label", "lat", "lon"],
            "k": 1,
        },
    )
    if not nearest.results:
        raise RuntimeError("15K replay found no checkpoint coordinate for the join")
    nearest_checkpoint = nearest.results[0].data
    checkpoint_id = str(nearest_checkpoint.get("candidate_id") or "").strip()
    if not checkpoint_id:
        raise RuntimeError("15K replay nearest checkpoint has no candidate_id")
    checkpoint_filter = execute(
        "contradiction_check",
        {
            "operation": "filter",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "predicates": [
                {"field": "candidate_id", "operator": "eq", "value": checkpoint_id}
            ],
            "fields": ["candidate_id", "label", "lat", "lon"],
            "limit": 2,
        },
    )
    anchor_freshness = execute(
        "freshness_check",
        {
            "operation": "freshness",
            "artifact": {"project_ref_key": "route_mileage_k_anchors_ref"},
            "stale_after_seconds": 31_536_000,
        },
    )
    checkpoint_freshness = execute(
        "freshness_check",
        {
            "operation": "freshness",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "stale_after_seconds": 31_536_000,
        },
    )
    manifest_verification = execute(
        "source_verification",
        {
            "operation": "inspect",
            "artifact": {"source_ref": "project.json"},
            "fields": [
                "route_mileage_k_anchors_ref",
                "checkpoint_candidates_ref",
            ],
        },
    )

    expected_refs = {
        "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
        "checkpoint_candidates_ref": "candidates/checkpoints.json",
    }
    manifest_fields = _selected_fields(manifest)
    verified_fields = _selected_fields(manifest_verification)
    anchor_hashes = _response_hashes(
        anchor_inspect,
        anchor_filter,
        anchor_count,
        anchor_freshness,
    )
    checkpoint_hashes = _response_hashes(
        checkpoint_inspect,
        nearest,
        checkpoint_filter,
        checkpoint_freshness,
    )
    source_verification = {
        "passed": (
            manifest_fields == expected_refs
            and verified_fields == expected_refs
            and len(anchor_hashes) == 1
            and len(checkpoint_hashes) == 1
            and checkpoint_filter.result_count == 1
        ),
        "manifest_fields": manifest_fields,
        "verified_manifest_fields": verified_fields,
        "anchor_source_hashes": sorted(anchor_hashes),
        "checkpoint_source_hashes": sorted(checkpoint_hashes),
    }
    if not source_verification["passed"]:
        raise RuntimeError("15K replay source verification failed")

    distance_m = _required_float(nearest_checkpoint, "distance_m")
    answer = (
        f"本次路徑 15K 位於 {lat:.9f}, {lon:.9f} "
        "[candidates/route_mileage_k_anchors.json]。"
        f"最近的 CP 是 {checkpoint_id}，距離約 {distance_m:.2f} 公尺 "
        "[candidates/checkpoints.json]。"
    )
    grounding = runtime.verify_synthesis(
        answer,
        evidence_cards=evidence_cards,
    )
    request_record = AgentRequestLedger(
        request_index=1,
        tool_call_count=len(call_trace),
        tool_result_chars=sum(len(card.model_dump_json()) for card in evidence_cards),
    )
    ledger = runtime.record_request(
        AgentRunLedger(budget=budget),
        request_record,
        selected_tool_ids=[WORKSPACE_QUERY_TOOL_ID],
        executed_tool_ids=[WORKSPACE_QUERY_TOOL_ID],
    )
    working = grounding.passed and ledger.budget_stop_reason is None
    return {
        "artifact_kind": "scout_ai_workspace_15k_join_replay",
        "evaluation_semantics": (
            "faithful_deterministic_workspace_replay_not_model_quality"
        ),
        "status": "completed" if working else "failed",
        "prototype_status": "WORKING PROTOTYPE" if working else "EXPERIMENT FAILED",
        "question": "本次路徑的 15K 在哪裡，座標與最近 CP 是什麼？",
        "budget": {
            "max_tool_calls": budget.max_tool_calls,
            "max_model_requests": budget.max_requests,
            "fresh_per_recovery_stage": True,
        },
        "call_trace": call_trace,
        "ledger": ledger.model_dump(mode="json"),
        "source_verification": source_verification,
        "grounding_verification": grounding.model_dump(mode="json"),
        "answer": answer,
        "tool_repair": {"performed": False, "reason": "trajectory_succeeded"},
        "model_switch": {"performed": False, "reason": "trajectory_succeeded"},
        "codex_review": {"performed": False, "reason": "trajectory_succeeded"},
        "known_issues": [],
    }


def _required_float(value: dict[str, Any], key: str) -> float:
    raw = value.get(key)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise RuntimeError(f"15K replay evidence is missing numeric {key}")
    return float(raw)


def _selected_fields(response: object) -> dict[str, Any]:
    results = getattr(response, "results", [])
    if not results:
        return {}
    data = getattr(results[0], "data", {})
    selected = data.get("selected_fields") if isinstance(data, dict) else None
    return dict(selected) if isinstance(selected, dict) else {}


def _response_hashes(*responses: object) -> set[str]:
    hashes: set[str] = set()
    for response in responses:
        for result in getattr(response, "results", []):
            source_hash = getattr(result, "source_hash", None)
            if isinstance(source_hash, str) and source_hash:
                hashes.add(source_hash)
    return hashes


def _deterministic_tool_args(
    tool: object,
    *,
    prompt: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Generate stable composition queries instead of random invalid unions."""

    if getattr(tool, "name", None) != "query_scout_workspace":
        return fallback
    expected_match = re.search(
        r"Expected deterministic workspace operations:\n(\[[^\n]*\])",
        prompt,
    )
    expected: list[str] = []
    if expected_match is not None:
        try:
            value = json.loads(expected_match.group(1))
        except json.JSONDecodeError:
            value = []
        if isinstance(value, list):
            expected = [str(item) for item in value]
    if "count" in expected:
        ref_key = (
            "checkpoint_candidates_ref"
            if "CP" in prompt or "checkpoint" in prompt.casefold()
            else "route_summary_ref"
        )
        return {
            "request": {
                "operation": "count",
                "artifact": {"project_ref_key": ref_key},
            }
        }
    return fallback


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
        "--workspace-15k-join-replay",
        action="store_true",
        help=(
            "Run the focused 15K mileage-anchor to nearest-CP evidence replay "
            "instead of the 100-case comparison."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_REPLAY_TIMEOUT_SECONDS,
    )
    args = parser.parse_args(argv)

    if args.workspace_15k_join_replay:
        project_root = args.workspace_root / args.project_id
        report = run_workspace_15k_join_replay(project_root)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / "workspace_15k_join_replay.json"
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output_path.chmod(0o600)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "prototype_status": report["prototype_status"],
                    "output": str(output_path),
                    "answer": report["answer"],
                },
                ensure_ascii=False,
            )
        )
        return 0 if report["status"] == "completed" else 1

    cases = load_eval_cases(args.cases_file)
    before_report = json.loads(args.before_report.read_text(encoding="utf-8"))
    runner = DeterministicProgressiveReplayRunner()
    after_report = run_live_tool_selection_eval(
        cases=cases,
        runner=runner,
        project_id=args.project_id,
        workspace_root=args.workspace_root,
        timeout_seconds=args.timeout_seconds,
        max_context_chars=DEFAULT_REPLAY_MAX_CONTEXT_CHARS,
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
