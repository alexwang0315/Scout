"""Readiness gate and live 100-case runner for Scout L5 Code Mode."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolReturnPart

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_pydantic_provider import (  # noqa: E402
    BOUNDED_AGENT_SYSTEM_POLICY,
    ScoutWorkspaceToolContext,
)
from pydantic_ai_runtime_compat import (  # noqa: E402
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_result_output,
    pydantic_usage_limits_from_budget,
)
from scout.schemas.agent_runtime import (  # noqa: E402
    AgentRunBudget,
    EvidenceCard,
    QuestionClass,
)
from scout.schemas.l5_code_mode import (  # noqa: E402
    L5ActivationRequest,
    L5RuntimeStatus,
)
from scout.schemas.workspace_query import WorkspaceQueryResponse  # noqa: E402
from scout.services.bounded_agent_runtime import BoundedAgentRuntime  # noqa: E402
from scout.services.agent_budget_policy import AgentBudgetPolicy  # noqa: E402
from scout.services.l5_code_mode import (  # noqa: E402
    build_l5_code_mode_capability,
    detect_l5_code_mode_runtime,
    validate_l5_project_root,
)
from scout.services.l5_code_mode_execution import (  # noqa: E402
    L5_ALLOWED_TOOL_IDS,
    MAX_L5_NESTED_TOOL_CALLS,
    build_l5_execution_receipt,
    l5_tool_metadata,
)
from scout_workspace_query_tool import WORKSPACE_QUERY_TOOL_ID  # noqa: E402
from scout_ai_tool_planner import plan_scout_ai_tools  # noqa: E402
from tools.scout_ai_live_tool_selection_eval import (  # noqa: E402
    EvalCase,
    load_env_file,
    load_eval_cases,
    run_live_tool_selection_eval,
    write_report,
)
from tools.scout_ai_workspace_query_eval import (  # noqa: E402
    WorkspaceQueryGoldLabel,
    grade_workspace_query_responses,
    load_workspace_query_gold_labels,
)

DEFAULT_CASES_FILE = (
    ROOT
    / "outputs"
    / "evals"
    / "scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json"
)
DEFAULT_GOLD_FILE = ROOT / "tests" / "fixtures" / "scout_ai_workspace_query_gold_100.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "evals" / "l5_code_mode"
DEFAULT_WORKSPACE_ROOT = Path("/Users/alexwang0315/workspace")
DEFAULT_PROJECT_ID = "chilai_nanhua_day1_scoutAI"
DEFAULT_L5_MODEL = "openrouter:poolside/laguna-m.1:free"
L5_MAX_REQUESTS = 10
L5_MAX_TOOL_CALLS = 10
L5_MAX_INPUT_TOKENS: int | None = None
L5_MAX_OUTPUT_TOKENS: int | None = None
L5_MAX_TOTAL_TOKENS: int | None = None


class L5EvalReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: str = "scout_l5_code_mode_eval_readiness"
    status: str
    ready: bool
    summary: str
    case_count: int = Field(ge=0)
    expected_case_count: int = Field(ge=1)
    project_id: str
    runtime: L5RuntimeStatus
    allowed_tool_ids: list[str]
    blockers: list[str]
    next_actions: list[str]
    artifacts: list[str]


class L5CodeModeEvalRunner:
    """Pydantic AI runner exposing one confined host query tool through Monty."""

    evaluation_semantics = "l5_code_mode_grounded_answer_quality"
    calls_every_disclosed_tool = False

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str | None,
        api_key: str | None,
        receipt_sink: list[dict[str, Any]] | None = None,
        model_max_tokens: int | None = None,
        max_attempts: int = 10,
    ) -> None:
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.model_max_tokens = model_max_tokens
        self.max_attempts = max(1, max_attempts)
        self._attempt_index = 1
        self._receipt_sink = receipt_sink if receipt_sink is not None else []
        self.last_model_usage: dict[str, int] = {}
        self.last_model_response_metadata: dict[str, str] = {}
        self.last_agent_run_ledger: dict[str, Any] = {}
        self.last_evidence_cards: list[dict[str, Any]] = []
        self.last_grounding_verification: dict[str, Any] = {}
        self.last_context_handles: list[dict[str, Any]] = []
        self.last_l5_execution_receipt: dict[str, Any] = {}

    def clone_for_isolated_run(self) -> "L5CodeModeEvalRunner":
        return type(self)(
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            receipt_sink=self._receipt_sink,
            model_max_tokens=self.model_max_tokens,
            max_attempts=self.max_attempts,
        )

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        last_error: Exception | None = None
        last_output = ""
        previous_no_progress_signature: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._attempt_index = attempt
            if attempt > 1:
                tool_context.invocations = []
            self.last_evidence_cards = []
            self.last_grounding_verification = {}
            self.last_l5_execution_receipt = {}
            try:
                last_output = self._run_once_with_workspace_tools(
                    prompt,
                    timeout_seconds=timeout_seconds,
                    tool_context=tool_context,
                )
            except Exception as exc:
                last_error = exc
                signature = _l5_no_progress_signature(
                    self.last_l5_execution_receipt,
                    self.last_grounding_verification,
                    self.last_evidence_cards,
                )
                if (
                    signature is not None
                    and signature == previous_no_progress_signature
                ):
                    return last_output
                previous_no_progress_signature = signature
                if attempt < self.max_attempts and _retryable_l5_error(exc):
                    continue
                raise
            if _l5_attempt_succeeded(
                self.last_grounding_verification,
                self.last_l5_execution_receipt,
            ):
                return last_output
            signature = _l5_no_progress_signature(
                self.last_l5_execution_receipt,
                self.last_grounding_verification,
                self.last_evidence_cards,
            )
            if signature is not None and signature == previous_no_progress_signature:
                return last_output
            previous_no_progress_signature = signature
            if attempt == self.max_attempts:
                return last_output
        if last_error is not None:
            raise last_error
        return last_output

    def _run_once_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        del timeout_seconds
        project_root = tool_context._project_root()
        workspace_root = tool_context.pretrip_workspace_root
        if project_root is None or workspace_root is None:
            raise RuntimeError("l5_project_scope_unavailable")
        workspace_root = workspace_root.resolve()
        if workspace_root == project_root:
            workspace_root = project_root.parent
        activation_request = L5ActivationRequest(under_construction=True)
        capability = build_l5_code_mode_capability(
            project_root=project_root,
            workspace_root=workspace_root,
            activation_request=activation_request,
        )

        async def require_initial_code_mode_call(
            _ctx: object,
            request_context: object,
        ) -> object:
            messages = getattr(request_context, "messages", ())
            settings = dict(
                getattr(request_context, "model_settings", None) or {}
            )
            settings["tool_choice"] = _l5_tool_choice(messages)
            return replace(request_context, model_settings=settings)

        force_code_mode = Hooks(before_model_request=require_initial_code_mode_call)
        agent = Agent(
            build_chat_model(
                model_name=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
            ),
            system_prompt=_l5_system_prompt(),
            # CodeMode expands the tool surface first; the final hook then enforces
            # one bounded code phase followed by a no-tool synthesis request.
            capabilities=[capability, force_code_mode],
            **pydantic_agent_runtime_kwargs(),
        )
        tool_context.model_arguments_untrusted = True
        nested_call_count = 0
        planner_plan = plan_scout_ai_tools(
            tool_context.query,
            project_root=project_root,
            limit=8,
        )
        expected_operations = [
            operation.value for operation in planner_plan.expected_operations
        ]
        nested_tool_limit = _l5_nested_tool_limit(
            question_class=planner_plan.question_class,
            expected_operations=expected_operations,
        )
        manifest_ref_keys = _relevant_manifest_ref_keys(
            project_root,
            question=tool_context.query.question,
        )

        @agent.tool_plain(
            name="query_scout_workspace",
            description=(
                "Run a typed, deterministic, read-only query against the selected "
                "Scout project. Use returned source_refs and evidence records in answers."
            ),
            metadata=l5_tool_metadata(WORKSPACE_QUERY_TOOL_ID),
        )
        def query_scout_workspace(
            request: dict[str, object],
        ) -> dict[str, object]:
            nonlocal nested_call_count
            nested_call_count += 1
            if nested_call_count > nested_tool_limit:
                raise RuntimeError("l5_nested_tool_budget_exceeded")
            return tool_context.query_scout_workspace(request=dict(request))

        budget = AgentRunBudget(
            question_class=planner_plan.question_class,
            attempt_index=self._attempt_index,
            max_requests=L5_MAX_REQUESTS,
            max_tool_calls=L5_MAX_TOOL_CALLS,
            max_input_tokens=L5_MAX_INPUT_TOKENS,
            max_repairs=10,
            max_output_tokens=L5_MAX_OUTPUT_TOKENS,
            max_total_tokens=L5_MAX_TOTAL_TOKENS,
        )
        started = time.perf_counter()
        run_prompt = (
            f"{prompt}\nL5 deterministic planner expected operations: "
            f"{json.dumps(expected_operations, ensure_ascii=False)}. "
            "Available manifest project_ref_key values, relevance-ranked: "
            f"{json.dumps(manifest_ref_keys, ensure_ascii=False)}. "
            "Use only the minimum queries needed for those operations. A single-"
            "operation question should normally call query_scout_workspace once. "
            f"The hard nested-call limit for this question is {nested_tool_limit}."
        )
        try:
            model_settings = (
                {"max_tokens": self.model_max_tokens}
                if self.model_max_tokens is not None
                else None
            )
            result = agent.run_sync(
                run_prompt,
                model_settings=model_settings,
                usage_limits=pydantic_usage_limits_from_budget(budget),
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1_000, 3)
            receipt = build_l5_execution_receipt(
                result=None,
                activation_request=activation_request,
                project_id=project_root.name,
                prompt=run_prompt,
                duration_ms=duration_ms,
                stop_reason=f"model_run_{type(exc).__name__}",
                output_text="",
            )
            self.last_l5_execution_receipt = receipt.model_dump(mode="json")
            self._receipt_sink.append(
                {
                    "question": tool_context.query.question,
                    "attempt": self._attempt_index,
                    "receipt": self.last_l5_execution_receipt,
                    "workspace_responses": [
                        dict(item)
                        for item in tool_context.invocations
                        if item.get("tool_id") == WORKSPACE_QUERY_TOOL_ID
                    ],
                }
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1_000, 3)
        output = str(pydantic_result_output(result))
        runtime = BoundedAgentRuntime(budget=budget)
        cards = [
            runtime.evidence_from_tool_result(WORKSPACE_QUERY_TOOL_ID, invocation)
            for invocation in tool_context.invocations
            if invocation.get("tool_id") == WORKSPACE_QUERY_TOOL_ID
        ]
        self.last_evidence_cards = [card.model_dump(mode="json") for card in cards]
        verification = runtime.verify_synthesis(output, evidence_cards=cards)
        final_output = output
        if not verification.passed and cards:
            final_output = _deterministic_evidence_answer(cards)
            verification = runtime.verify_synthesis(
                final_output,
                evidence_cards=cards,
            )
        self.last_grounding_verification = verification.model_dump(mode="json")
        stop_reason = None
        if nested_call_count > nested_tool_limit:
            stop_reason = "nested_tool_call_limit_exceeded"
        receipt = build_l5_execution_receipt(
            result=result,
            activation_request=activation_request,
            project_id=project_root.name,
            prompt=run_prompt,
            duration_ms=duration_ms,
            stop_reason=stop_reason,
            output_text=final_output,
        )
        self.last_l5_execution_receipt = receipt.model_dump(mode="json")
        self._receipt_sink.append(
            {
                "question": tool_context.query.question,
                "attempt": self._attempt_index,
                "receipt": self.last_l5_execution_receipt,
                "evidence_cards": self.last_evidence_cards,
                "grounding_verification": self.last_grounding_verification,
                "workspace_responses": [
                    dict(item)
                    for item in tool_context.invocations
                    if item.get("tool_id") == WORKSPACE_QUERY_TOOL_ID
                ],
            }
        )
        self.last_model_usage = _serialize_usage(result)
        self.last_agent_run_ledger = {
            "budget": budget.model_dump(mode="json"),
            "request_count": self.last_model_usage.get("requests", 0),
            "tool_call_count": nested_call_count,
            "selected_tool_ids": [WORKSPACE_QUERY_TOOL_ID],
            "executed_tool_ids": [
                WORKSPACE_QUERY_TOOL_ID
                for _ in range(nested_call_count)
            ],
            "budget_stop_reason": receipt.stop_reason,
        }
        if not verification.passed:
            return "目前沒有足夠的可引用 Scout 證據，因此不提供未驗證答案。"
        return final_output


def check_l5_eval_readiness(
    *,
    cases_file: Path,
    workspace_root: Path,
    project_id: str,
    expected_case_count: int = 100,
) -> L5EvalReadiness:
    blockers: list[str] = []
    case_count = 0
    try:
        cases = load_eval_cases(cases_file)
        case_count = len(cases)
    except (OSError, ValueError, json.JSONDecodeError):
        cases = ()
        blockers.append("cases_file_invalid")
    if case_count != expected_case_count:
        blockers.append(f"expected_{expected_case_count}_cases_got_{case_count}")
    if len({case.case_id for case in cases}) != case_count:
        blockers.append("case_ids_not_unique")
    try:
        validate_l5_project_root(
            project_root=workspace_root / project_id,
            workspace_root=workspace_root,
        )
    except ValueError:
        blockers.append("project_manifest_unavailable")
    runtime = detect_l5_code_mode_runtime()
    if not runtime.available or not runtime.runtime_attested:
        blockers.append("l5_runtime_unavailable")
    ready = not blockers
    return L5EvalReadiness(
        status="success" if ready else "error",
        ready=ready,
        summary=(
            "L5 Code Mode is ready for the 100-case sequence."
            if ready
            else "L5 Code Mode readiness checks found blockers."
        ),
        case_count=case_count,
        expected_case_count=expected_case_count,
        project_id=project_id,
        runtime=runtime,
        allowed_tool_ids=sorted(L5_ALLOWED_TOOL_IDS),
        blockers=blockers,
        next_actions=(
            ["run_one_case_smoke", "run_operation_smoke", "run_100_cases"]
            if ready
            else ["resolve_blockers_and_repeat_readiness"]
        ),
        artifacts=[str(cases_file)],
    )


def augment_l5_report(
    report: dict[str, Any],
    receipts: list[dict[str, Any]],
    *,
    gold_labels: dict[str, WorkspaceQueryGoldLabel] | None = None,
    project_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipts_by_question: dict[str, list[dict[str, Any]]] = {}
    for item in receipts:
        receipt = item.get("receipt")
        if not isinstance(receipt, dict):
            continue
        receipts_by_question.setdefault(str(item.get("question")), []).append(item)
    samples: list[dict[str, Any]] = []
    for sample in report.get("samples", []):
        updated = dict(sample)
        attempts = receipts_by_question.get(str(sample.get("question")), [])
        receipt = attempts[-1].get("receipt") if attempts else None
        updated["l5_attempt_receipts"] = [
            item["receipt"]
            for item in attempts
            if isinstance(item.get("receipt"), dict)
        ]
        updated["l5_evidence_cards"] = (
            attempts[-1].get("evidence_cards", []) if attempts else []
        )
        updated["l5_attempt_grounding_verification"] = (
            attempts[-1].get("grounding_verification", {}) if attempts else {}
        )
        updated["l5_execution_receipt"] = receipt
        updated["l5_receipt_valid"] = isinstance(receipt, dict)
        updated["l5_attempt_count"] = len(attempts)
        label = (gold_labels or {}).get(str(sample.get("case_id")))
        updated["l5_semantic_grade"] = (
            _grade_l5_workspace_responses(
                label,
                list(attempts[-1].get("workspace_responses", [])),
                project_manifest or {},
            )
            if label is not None and attempts
            else None
        )
        samples.append(updated)
    valid_receipts = [
        item["l5_execution_receipt"]
        for item in samples
        if isinstance(item.get("l5_execution_receipt"), dict)
    ]
    case_count = len(samples)
    l5_metrics = {
        "receipt_valid_count": len(valid_receipts),
        "receipt_valid_rate": (
            round(len(valid_receipts) / case_count, 4) if case_count else 0.0
        ),
        "code_mode_call_count": sum(
            int(item.get("code_mode_call_count") or 0) for item in valid_receipts
        ),
        "nested_tool_call_count": sum(
            int(item.get("nested_tool_call_count") or 0) for item in valid_receipts
        ),
        "workspace_query_operation_count": sum(
            1
            for item in valid_receipts
            for call in item.get("nested_tool_calls", [])
            if isinstance(call, dict) and call.get("operation")
        ),
        "fail_closed_receipt_count": sum(
            1 for item in valid_receipts if item.get("status") == "fail_closed"
        ),
        "attempt_count": sum(
            int(item.get("l5_attempt_count") or 0) for item in samples
        ),
        "grounded_answer_count": sum(
            1
            for item in samples
            if (item.get("grounding_verification") or {}).get("passed") is True
        ),
        "semantic_evaluable_count": sum(
            1 for item in samples if isinstance(item.get("l5_semantic_grade"), dict)
        ),
        "semantic_pass_count": sum(
            1
            for item in samples
            if (item.get("l5_semantic_grade") or {}).get("passed") is True
        ),
    }
    return {
        **report,
        "artifact_kind": "scout_ai_l5_code_mode_eval",
        "evaluation_semantics": "l5_code_mode_grounded_answer_quality",
        "legacy_domain_tool_oracle_diagnostic_only": True,
        "l5_metrics": l5_metrics,
        "samples": samples,
    }


def _grade_l5_workspace_responses(
    label: WorkspaceQueryGoldLabel,
    raw_responses: list[dict[str, Any]],
    project_manifest: dict[str, Any],
) -> dict[str, Any]:
    responses: list[WorkspaceQueryResponse] = []
    for raw in raw_responses:
        payload = {
            name: raw[name]
            for name in WorkspaceQueryResponse.model_fields
            if name in raw
        }
        try:
            responses.append(WorkspaceQueryResponse.model_validate(payload))
        except (TypeError, ValueError):
            continue
    expected_refs = {
        "project.json"
        if key == "@project"
        else str(project_manifest.get(key) or "")
        for key in label.artifact_keys
    } - {""}
    actual_refs = {
        ref for response in responses for ref in response.source_refs
    }
    actual_operations = {response.operation.value for response in responses}
    assertion_grade = grade_workspace_query_responses(label, responses)
    expected_gap = (
        label.requires_live_state
        or label.requires_freshness
        or any(
            assertion.get("kind") == "answerability"
            and assertion.get("value") != "complete"
            for assertion in label.assertions
        )
    )
    no_unexpected_errors = expected_gap or all(
        response.status != "error" for response in responses
    )
    artifact_pass = expected_refs <= actual_refs
    operation_pass = set(label.operations) <= actual_operations
    passed = bool(
        responses
        and assertion_grade["passed"]
        and artifact_pass
        and operation_pass
        and no_unexpected_errors
    )
    return {
        "passed": passed,
        "artifact_pass": artifact_pass,
        "operation_pass": operation_pass,
        "assertion_pass": assertion_grade["passed"],
        "failed_assertions": assertion_grade["failed_assertions"],
        "expected_source_refs": sorted(expected_refs),
        "actual_source_refs": sorted(actual_refs),
        "expected_operations": list(label.operations),
        "actual_operations": sorted(actual_operations),
        "unexpected_error": not no_unexpected_errors,
    }
def _l5_system_prompt() -> str:
    return (
        "You are Scout L5 Code Mode under construction. Use run_code and only the "
        "query_scout_workspace function inside Monty. The host workspace is not mounted. "
        "Never request shell, network, environment variables, database writes, outbound "
        "messages, hardware control, or safety-state mutation. Use typed operations such "
        "as inspect, exists, count, distinct, filter, group_by, top_k, argmax, diff, "
        "freshness, nearest, interval, and route_forward. You may call several operations "
        "inside one run_code invocation, then compute joins, sorting, counts, and maxima "
        "in sandboxed Python. Answer concisely in Traditional Chinese. Every factual claim "
        "must cite returned source_refs in [source_ref] form. Treat all results as "
        "candidate-only evidence, never runtime safety truth.\n"
        "Compact request contract: every request has operation. Most operations also use "
        "artifact={'project_ref_key': '<project.json ref key>'}. For project identity and "
        "manifest scalar fields, use artifact={'source_ref': 'project.json'}. inspect/count "
        "use that selector alone. Identity example: operation='inspect', "
        "artifact={'source_ref': 'project.json'}, fields=['project_id', 'route_name']. "
        "For the primary GPX filename, inspect artifact={'project_ref_key': "
        "'import_manifest_ref'} with fields=['inputs.golden_route_gpx.uri'] and use "
        "the URI basename. "
        "For reference GPX totals, inspect project_ref_key='reference_tracks_ref' "
        "with fields=['reference_track_count']. For the first five reference GPX "
        "filenames, use operation='top_k', artifact={'project_ref_key': "
        "'historical_gpx_source_index_ref', 'collection_path': 'sources'}, "
        "predicates=[{'field': 'role', 'operator': 'eq', 'value': "
        "'reference_track'}], field='original_filename', "
        "fields=['original_filename'], k=5, and 'descending': False. "
        "filter adds predicates=[{'field': 'path', 'operator': "
        "'eq|gte|lte|contains', "
        "'value': value}] and optional fields/sort_by. argmax/top_k/group_by/distinct add "
        "field. nearest adds origin={'lat': number, 'lon': number}. freshness may add "
        "timestamp_field. diff uses left_artifact and right_artifact. interval supplies "
        "one valid range, containment, or cumulative mode. Use an inspect query first only "
        "when the artifact collection/fields are genuinely unknown.\n"
        f"{BOUNDED_AGENT_SYSTEM_POLICY}"
    )


def _l5_tool_choice(messages: object) -> str:
    """Require one code phase, then force a bounded text synthesis phase."""

    has_code_result = any(
        isinstance(part, ToolReturnPart) and part.tool_name == "run_code"
        for message in messages if hasattr(messages, "__iter__")
        for part in getattr(message, "parts", ())
    )
    return "none" if has_code_result else "required"


def _l5_nested_tool_limit(
    *,
    question_class: QuestionClass,
    expected_operations: tuple[str, ...] | list[str],
) -> int:
    """Apply a complexity-scaled nested-query cap beneath the global L5 ceiling."""

    budget = AgentBudgetPolicy.for_query(
        question_class=question_class,
        expected_operations=expected_operations,
        selected_tool_ids=(WORKSPACE_QUERY_TOOL_ID,),
        requires_join=question_class
        in {
            QuestionClass.CROSS_ARTIFACT_JOIN,
            QuestionClass.WEATHER_TERRAIN_COMPOUND,
        },
        requires_live_state=question_class
        in {QuestionClass.LIVE_RUNTIME_FACT, QuestionClass.SAFETY_DECISION},
    )
    return min(MAX_L5_NESTED_TOOL_CALLS, max(6, budget.max_tool_calls))


def _serialize_usage(result: object) -> dict[str, int]:
    usage_method = getattr(result, "usage", None)
    usage = usage_method() if callable(usage_method) else None
    output: dict[str, int] = {}
    for key in ("requests", "tool_calls", "input_tokens", "output_tokens"):
        value = getattr(usage, key, None)
        if isinstance(value, int):
            output[key] = value
    return output


def _retryable_l5_error(exc: Exception) -> bool:
    return type(exc).__name__ in {
        "ModelHTTPError",
        "UnexpectedModelBehavior",
        "UsageLimitExceeded",
    }


def _l5_no_progress_signature(
    execution_receipt: dict[str, Any],
    grounding_verification: dict[str, Any],
    evidence_cards: list[dict[str, Any]],
) -> str | None:
    """Identify repeated failed stages that produced no new evidence.

    Ten attempts remain available, but an identical evidence-free failure should
    advance the recovery ladder instead of consuming the remaining capacity.
    """

    if evidence_cards or grounding_verification.get("passed") is True:
        return None
    nested_calls = execution_receipt.get("nested_tool_calls") or []
    payload = {
        "status": execution_receipt.get("status"),
        "stop_reason": execution_receipt.get("stop_reason"),
        "code_mode_call_count": execution_receipt.get("code_mode_call_count"),
        "nested_tool_call_count": execution_receipt.get("nested_tool_call_count"),
        "nested_operations": [
            {
                "operation": item.get("operation"),
                "status": item.get("status"),
                "error": item.get("error"),
            }
            for item in nested_calls
            if isinstance(item, dict)
        ],
        "grounding_reason": grounding_verification.get("reason"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _l5_attempt_succeeded(
    grounding_verification: dict[str, Any],
    execution_receipt: dict[str, Any],
) -> bool:
    return (
        grounding_verification.get("passed") is True
        and execution_receipt.get("status") == "success"
    )


def _relevant_manifest_ref_keys(
    project_root: Path,
    *,
    question: str,
    limit: int = 24,
) -> list[str]:
    """Disclose only safe manifest key names, never their paths or payloads."""

    try:
        payload = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    blocked = ("secret", "token", "credential", "password", "private", "key")
    keys = [
        str(key)
        for key, value in payload.items()
        if isinstance(value, str)
        and str(key).endswith("_ref")
        and not any(fragment in str(key).casefold() for fragment in blocked)
    ]
    normalized = question.casefold()
    aliases = {
        "checkpoint": ("cp", "checkpoint", "檢查點"),
        "segment": ("segment", "路段", "分段"),
        "route": ("route", "路線", "航線"),
        "risk": ("risk", "風險", "危險"),
        "weather": ("weather", "天氣", "氣象"),
        "cwa": ("cwa", "氣象署", "警報"),
        "terrain": ("terrain", "地形", "坡度", "高程"),
        "mcp": ("mcp", "里程牌"),
        "boss": ("boss", "山頭"),
        "rain": ("rain", "雨", "降水"),
        "review": ("review", "審核", "人工"),
        "map": ("map", "地圖", "圖層"),
        "poi": ("poi", "興趣點", "地標"),
        "import": ("import", "匯入", "來源類型"),
        "manifest": ("manifest", "清單", "檔案數量"),
        "catalog": ("catalog", "目錄", "workspace"),
        "reference": ("reference", "參考", "對照"),
        "gpx": ("gpx", "軌跡", "航跡"),
    }
    query_terms = {
        term
        for canonical, variants in aliases.items()
        if any(variant in normalized for variant in variants)
        for term in (canonical,)
    }

    def score(key: str) -> tuple[int, str]:
        normalized_key = key.casefold()
        relevance = sum(1 for term in query_terms if term in normalized_key)
        if "checkpoint" in query_terms and "checkpoint_candidates" in normalized_key:
            relevance += 4
        if "segment" in query_terms and "segment_candidates" in normalized_key:
            relevance += 4
        if "route" in query_terms and "route_summary" in normalized_key:
            relevance += 3
        if {"reference", "gpx"} <= query_terms and "reference_tracks" in normalized_key:
            relevance += 8
        if "gpx" in query_terms and "historical_gpx_source_index" in normalized_key:
            relevance += 4
        return (-relevance, key)

    return sorted(keys, key=score)[:limit]


def _deterministic_evidence_answer(cards: list[EvidenceCard]) -> str:
    """Produce the quick-answer contract directly from verified evidence cards."""

    sentences: list[str] = []
    for card in cards:
        status = str(card.key_values.get("status") or "").casefold()
        if status in {"error", "failed"} or not card.source_refs:
            continue
        values: list[object] = []
        for record in card.evidence_records[:5]:
            record_values = record.data.get("selected_fields", record.data)
            if cleaned := _clean_answer_value(record_values):
                values.append(cleaned)
        if not values and card.key_values:
            if cleaned := _clean_answer_value(card.key_values):
                values.append(cleaned)
        fragments = []
        if card.claim_summary.strip():
            fragments.append(card.claim_summary.strip())
        fragments.extend(
            _format_answer_value(value)
            for value in values
        )
        if not fragments:
            continue
        citations = " ".join(f"[{ref}]" for ref in dict.fromkeys(card.source_refs))
        sentences.append(f"{'；'.join(dict.fromkeys(fragments))} {citations}".strip())
    return "\n".join(sentences) or "目前沒有足夠的可引用 Scout 證據。"


def _clean_answer_value(value: object) -> object | None:
    if value == "[nested content omitted]":
        return None
    if isinstance(value, str) and Path(value).is_absolute():
        return Path(value).name
    if isinstance(value, dict):
        blocked = {
            "artifact_kind",
            "tool_id",
            "status",
            "answerability",
            "operation",
            "summary",
            "results",
            "freshness",
        }
        cleaned = {
            str(key): child
            for key, item in value.items()
            if key not in blocked
            if (child := _clean_answer_value(item)) is not None
        }
        return cleaned or None
    if isinstance(value, list):
        cleaned_items = [
            child
            for item in value
            if (child := _clean_answer_value(item)) is not None
        ]
        return cleaned_items or None
    return value


def _format_answer_value(value: object) -> str:
    """Render evidence without square brackets that look like source citations."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True).translate(
        str.maketrans({"[": "(", "]": ")"})
    )


def _select_cases(
    cases: tuple[EvalCase, ...],
    *,
    case_ids: list[str],
    offset: int,
    max_cases: int | None,
) -> tuple[EvalCase, ...]:
    selected = cases
    if case_ids:
        requested = set(case_ids)
        selected = tuple(case for case in selected if case.case_id in requested)
        missing = requested - {case.case_id for case in selected}
        if missing:
            raise ValueError(f"Unknown --case-id values: {sorted(missing)}")
    selected = selected[offset:]
    return selected[:max_cases] if max_cases is not None else selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--cases-file", type=Path, default=DEFAULT_CASES_FILE)
    parser.add_argument("--gold-file", type=Path, default=DEFAULT_GOLD_FILE)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--expected-case-count", type=int, default=100)
    parser.add_argument("--model", default=DEFAULT_L5_MODEL)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env-var", default="OPENROUTER_API_KEY")
    parser.add_argument("--allow-missing-api-key", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--case-offset", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--model-max-tokens", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--max-context-chars", type=int, default=None)
    parser.add_argument("--delay-between-cases-seconds", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    readiness = check_l5_eval_readiness(
        cases_file=args.cases_file,
        workspace_root=args.workspace_root,
        project_id=args.project_id,
        expected_case_count=args.expected_case_count,
    )
    if args.check or not readiness.ready:
        print(readiness.model_dump_json(indent=2))
        return 0 if readiness.ready else 2
    if args.case_offset < 0:
        raise SystemExit("--case-offset must be >= 0")
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts must be >= 1")
    os.environ.update(load_env_file(args.env_file))
    api_key = os.environ.get(args.api_key_env_var)
    if not api_key and not args.allow_missing_api_key:
        raise SystemExit(f"{args.api_key_env_var} is missing; not running live L5 eval")
    cases = _select_cases(
        load_eval_cases(args.cases_file),
        case_ids=args.case_id,
        offset=args.case_offset,
        max_cases=args.max_cases,
    )
    gold_labels = {
        label.case_id: label
        for label in load_workspace_query_gold_labels(
            args.gold_file,
            cases_path=args.cases_file,
        )
    }
    project_manifest = json.loads(
        (args.workspace_root / args.project_id / "project.json").read_text(
            encoding="utf-8"
        )
    )
    receipt_sink: list[dict[str, Any]] = []
    runner = L5CodeModeEvalRunner(
        model_name=args.model,
        base_url=args.base_url,
        api_key=api_key,
        receipt_sink=receipt_sink,
        model_max_tokens=args.model_max_tokens,
        max_attempts=args.max_attempts,
    )
    report = run_live_tool_selection_eval(
        cases=cases,
        runner=runner,
        project_id=args.project_id,
        workspace_root=args.workspace_root,
        timeout_seconds=args.timeout_seconds,
        max_context_chars=args.max_context_chars,
        delay_between_cases_seconds=max(0.0, args.delay_between_cases_seconds),
    )
    report = augment_l5_report(
        report,
        receipt_sink,
        gold_labels=gold_labels,
        project_manifest=project_manifest,
    )
    json_path, markdown_path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "status": "completed",
                "case_count": report["case_count"],
                "l5_metrics": report["l5_metrics"],
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
            },
            ensure_ascii=False,
        )
    )
    metrics = report["l5_metrics"]
    passed = (
        metrics["receipt_valid_count"] == report["case_count"]
        and metrics["fail_closed_receipt_count"] == 0
        and metrics["grounded_answer_count"] == report["case_count"]
        and metrics["semantic_evaluable_count"] == report["case_count"]
        and metrics["semantic_pass_count"] == report["case_count"]
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
