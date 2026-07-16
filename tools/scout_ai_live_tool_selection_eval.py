from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from assistant_pydantic_provider import (  # noqa: E402
    PydanticAIEnvRunner,
    ScoutWorkspaceToolContext,
    build_bounded_assistant_prompt,
)
from scout.schemas.agent_runtime import EvidenceCard  # noqa: E402
from scout.services.bounded_agent_runtime import BoundedAgentRuntime  # noqa: E402
from scout_ai_context_registry import discover_scout_ai_context_sources  # noqa: E402
from scout_ai_tool_planner import plan_scout_ai_tools  # noqa: E402

ARTIFACT_KIND = "scout_ai_live_tool_selection_eval"
ARTIFACT_VERSION = "scout_ai_live_tool_selection_eval.v0"
DEFAULT_MODEL = "openrouter:z-ai/glm-5.2"
DEFAULT_PROJECT_ID = "chilai_nanhua_day1"
DEFAULT_WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "scout_ai_live_tool_selection"
CONTEXT_HANDLE_EVAL_WIDTH = 10
INTERNAL_COMPOSITION_TOOL_IDS = frozenset({"scout.ai.workspace.query.v1"})
SECRET_NAME_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(r"(?i)\b(?:sk-|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*\S+"
    ),
)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])/(?:Users|home|data|private|tmp|var)/[^\s\"']+"
)
URL_PATTERN = re.compile(r"https?://[^\s\]\)\"']+")


class EvalCaseTimeout(TimeoutError):
    pass


def _raise_eval_case_timeout(signum: int, frame: object) -> None:
    raise EvalCaseTimeout("Scout AI eval case timed out")


class WorkspaceToolRunner(Protocol):
    model_name: str
    base_url: str | None
    last_workspace_tool_invocations: list[dict[str, object]]
    last_model_usage: dict[str, int]
    last_model_response_metadata: dict[str, str]
    last_agent_run_ledger: dict[str, Any]
    last_agent_recovery: dict[str, Any]
    last_context_handles: list[dict[str, Any]]
    last_evidence_cards: list[dict[str, Any]]
    last_grounding_verification: dict[str, Any]

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        ...


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    required_tool_ids: tuple[str, ...]
    notes: str = ""


WEATHER_GEO_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "natural weather visibility question should call weather and CWA evidence",
    ),
    EvalCase(
        "field-032",
        "現在風雨是否會放大失溫風險？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "wind/rain/cold compound question should include CWA and hydrologic background",
    ),
    EvalCase(
        "field-034",
        "這段如果起霧會不會容易失向？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "fog navigation uncertainty should at least call weather and CWA evidence",
    ),
    EvalCase(
        "field-035",
        "今天的天氣窗口是否足夠？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "weather window question should call official weather evidence",
    ),
    EvalCase(
        "field-036",
        "溪水暴漲會不會阻斷路線？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "stream surge question should include CWA plus GEE antecedent rain/hydrology",
    ),
    EvalCase(
        "field-037",
        "這段下雨後會變成落石區嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "rain plus rockfall question should include hydrologic background",
    ),
    EvalCase(
        "field-039",
        "風寒和濕衣是否已經構成風險？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "wind chill/wet clothing question should call weather and CWA evidence",
    ),
    EvalCase(
        "seed-027",
        "哪些地方下雨後風險會變高？",
        (
            "pydantic_ai.tool.search_scout_risk_scores.v0",
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "rain risk locations should include risk scores, weather, CWA, and GEE",
    ),
    EvalCase(
        "seed-088",
        "天氣與地形風險是否重疊？",
        (
            "pydantic_ai.tool.search_scout_risk_scores.v0",
            "pydantic_ai.tool.search_scout_terrain_scores.v0",
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "weather terrain overlap should include risk, terrain, weather, CWA, and GEE",
    ),
    EvalCase(
        "seed-089",
        "是否需要延後出發？",
        (
            "scout.ai.route_readiness.assess.v0",
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "departure delay question should use readiness and environment evidence",
    ),
)


def load_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def load_eval_cases(path: Path) -> tuple[EvalCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_cases = payload.get("cases")
    else:
        raw_cases = payload
    if not isinstance(raw_cases, list):
        raise ValueError("cases file must contain a list or a {cases: [...]} object")
    cases: list[EvalCase] = []
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"case {index} must be an object")
        case_id = str(item.get("case_id") or item.get("id") or "").strip()
        question = str(item.get("question") or "").strip()
        required_tool_ids = item.get("required_tool_ids") or item.get("expected_tool_ids") or []
        if not case_id or not question:
            raise ValueError(f"case {index} must include case_id/id and question")
        if not isinstance(required_tool_ids, list):
            raise ValueError(f"case {case_id} required_tool_ids must be a list")
        cases.append(
            EvalCase(
                case_id=case_id,
                question=question,
                required_tool_ids=tuple(str(tool_id) for tool_id in required_tool_ids),
                notes=str(item.get("notes") or item.get("data_family") or ""),
            )
        )
    return tuple(cases)


def run_live_tool_selection_eval(
    *,
    cases: tuple[EvalCase, ...] = WEATHER_GEO_CASES,
    runner: WorkspaceToolRunner,
    project_id: str = DEFAULT_PROJECT_ID,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
    timeout_seconds: int = 0,
    max_context_chars: int | None = None,
    delay_between_cases_seconds: float = 0.0,
) -> dict[str, Any]:
    started_at = _utc_now()
    samples = []
    for index, case in enumerate(cases, start=1):
        print(
            f"[scout-ai-eval] case {index}/{len(cases)} {case.case_id}",
            file=sys.stderr,
            flush=True,
        )
        sample = _run_one_case(
            case,
            runner=runner,
            project_id=project_id,
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
            max_context_chars=max_context_chars,
        )
        samples.append(sample)
        if delay_between_cases_seconds > 0 and index < len(cases):
            time.sleep(delay_between_cases_seconds)
    tool_selection_passed_count = sum(
        1 for sample in samples if sample["required_tools_selected"]
    )
    passed_count = sum(1 for sample in samples if sample["case_passed"])
    failed_count = len(samples) - passed_count
    answer_completed_count = sum(
        1 for sample in samples if sample["answer_completed"]
    )
    model_usage_totals = _sum_model_usage(samples)
    exact_set_match_count = sum(
        1 for sample in samples if sample["exact_required_tool_set_match"]
    )
    total_required = sum(len(sample["required_tool_ids"]) for sample in samples)
    total_required_found = sum(
        len(sample["required_tool_ids"]) - len(sample["missing_required_tool_ids"])
        for sample in samples
    )
    agent_run_ledger_totals = _sum_agent_run_ledgers(samples)
    context_evaluable = [
        sample for sample in samples if sample["context_top3_recall"] is not None
    ]
    context_hit_count = sum(
        1 for sample in context_evaluable if sample["context_top3_hit"]
    )
    context_required_count = sum(
        len(sample["context_evaluable_required_tool_ids"])
        for sample in context_evaluable
    )
    context_found_count = sum(
        len(sample["context_found_required_tool_ids"])
        for sample in context_evaluable
    )
    context_exact_count = sum(
        1 for sample in context_evaluable if sample["context_top3_exact_match"]
    )
    failure_category_counts: dict[str, int] = {}
    failure_class_counts: dict[str, int] = {}
    for sample in samples:
        category = str(sample["failure_category"])
        failure_category_counts[category] = failure_category_counts.get(category, 0) + 1
        failure_class = str(sample["failure_class"])
        failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
    evaluation_semantics = str(
        getattr(
            runner,
            "evaluation_semantics",
            "live_model_native_tool_selection_quality",
        )
    )
    calls_every_disclosed_tool = bool(
        getattr(runner, "calls_every_disclosed_tool", False)
    )
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "artifact_sensitivity": "sensitive_local_eval",
        "started_at": started_at,
        "finished_at": _utc_now(),
        "project_id": project_id,
        "workspace_root": workspace_root.name,
        "model": getattr(runner, "model_name", "unknown"),
        "base_url": _safe_eval_endpoint(getattr(runner, "base_url", None)),
        "evaluation_semantics": evaluation_semantics,
        "case_count": len(samples),
        "tool_selection_passed_count": tool_selection_passed_count,
        "tool_selection_pass_rate": (
            round(tool_selection_passed_count / len(samples), 4) if samples else 0.0
        ),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "pass_rate": round(passed_count / len(samples), 4) if samples else 0.0,
        "answer_completed_count": answer_completed_count,
        "answer_completion_rate": (
            round(answer_completed_count / len(samples), 4) if samples else 0.0
        ),
        "user_visible_unsupported_claim_count": sum(
            len(sample["user_visible_unsupported_claims"])
            for sample in samples
        ),
        "rejected_draft_claim_count": sum(
            int(
                (sample.get("grounding_verification") or {}).get(
                    "rejected_draft_claim_count"
                )
                or 0
            )
            for sample in samples
        ),
        "model_usage_totals": model_usage_totals,
        "tool_recall_macro": (
            round(sum(sample["tool_recall"] for sample in samples) / len(samples), 4)
            if samples
            else 0.0
        ),
        "tool_recall_micro": (
            round(total_required_found / total_required, 4)
            if total_required
            else 1.0
        ),
        "exact_set_match_count": exact_set_match_count,
        "exact_set_match_rate": (
            round(exact_set_match_count / len(samples), 4) if samples else 0.0
        ),
        "agent_run_ledger_totals": agent_run_ledger_totals,
        "context_top3_evaluable_count": len(context_evaluable),
        "context_top3_hit_count": context_hit_count,
        "context_top3_recall": (
            round(context_found_count / context_required_count, 4)
            if context_required_count
            else None
        ),
        "context_top3_macro_recall": (
            round(
                sum(sample["context_top3_recall"] for sample in context_evaluable)
                / len(context_evaluable),
                4,
            )
            if context_evaluable
            else None
        ),
        "context_top3_any_hit_rate": (
            round(context_hit_count / len(context_evaluable), 4)
            if context_evaluable
            else None
        ),
        "context_top3_exact_match_count": context_exact_count,
        "context_top3_exact_match_rate": (
            round(context_exact_count / len(context_evaluable), 4)
            if context_evaluable
            else None
        ),
        "failure_category_counts": dict(sorted(failure_category_counts.items())),
        "failure_class_counts": dict(sorted(failure_class_counts.items())),
        "pacing": {
            "delay_between_cases_seconds": delay_between_cases_seconds,
        },
        "scoring_policy": {
            "counts_only_model_native_tool_calls": True,
            "deterministic_planner_used_as_expected_tool_oracle_only": True,
            "assistant_api_pre_augmentation_used": False,
            "provider_keyword_auto_augmentation_used": False,
            "calls_every_disclosed_tool": calls_every_disclosed_tool,
        },
        "samples": samples,
    }


def _run_one_case(
    case: EvalCase,
    *,
    runner: WorkspaceToolRunner,
    project_id: str,
    workspace_root: Path,
    timeout_seconds: int,
    max_context_chars: int | None,
) -> dict[str, Any]:
    clone_for_isolated_run = getattr(runner, "clone_for_isolated_run", None)
    case_runner = (
        clone_for_isolated_run()
        if callable(clone_for_isolated_run)
        else runner
    )
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=case.question,
        project_id=project_id,
    )
    prompt = build_bounded_assistant_prompt(
        query,
        sources=[],
        max_context_chars=max_context_chars,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(
        query,
        sources=[],
        environ={"SCOUT_PRETRIP_WORKSPACE_ROOT": str(workspace_root)},
    )
    planned = plan_scout_ai_tools(
        query,
        project_root=workspace_root / project_id,
        limit=10,
    )
    planned_tool_ids = [item.tool_id for item in planned.selected_tools]
    started_at = _utc_now()
    t0 = time.perf_counter()
    output = ""
    error: dict[str, str] | None = None
    previous_handler: signal.Handlers | int | None = None
    try:
        if timeout_seconds > 0 and hasattr(signal, "SIGALRM"):
            previous_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _raise_eval_case_timeout)
            signal.alarm(timeout_seconds)
        output = case_runner.run_with_workspace_tools(
            prompt,
            timeout_seconds=timeout_seconds,
            tool_context=tool_context,
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": _redact(str(exc))}
    finally:
        if timeout_seconds > 0 and hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            if previous_handler is not None:
                signal.signal(signal.SIGALRM, previous_handler)
    latency_ms = round((time.perf_counter() - t0) * 1000, 3)
    invocations = [
        invocation
        for invocation in tool_context.invocations
        if isinstance(invocation, dict)
    ]
    all_native_tool_ids = [
        str(invocation.get("tool_id") or "")
        for invocation in invocations
        if invocation.get("tool_id")
    ]
    internal_composition_tool_ids = [
        tool_id
        for tool_id in all_native_tool_ids
        if tool_id in INTERNAL_COMPOSITION_TOOL_IDS
    ]
    native_tool_ids = [
        tool_id
        for tool_id in all_native_tool_ids
        if tool_id not in INTERNAL_COMPOSITION_TOOL_IDS
    ]
    required = list(case.required_tool_ids)
    missing_required = [tool_id for tool_id in required if tool_id not in native_tool_ids]
    required_tools_selected = not missing_required
    seen_native: set[str] = set()
    extra_native = []
    for tool_id in native_tool_ids:
        if tool_id not in required or tool_id in seen_native:
            extra_native.append(tool_id)
        seen_native.add(tool_id)
    exact_required_tool_set_match = (
        len(native_tool_ids) == len(required)
        and set(native_tool_ids) == set(required)
    )
    tool_recall = (
        round((len(required) - len(missing_required)) / len(required), 4)
        if required
        else 1.0
    )
    unexpected_native = [
        tool_id for tool_id in native_tool_ids if tool_id not in planned_tool_ids
    ]
    model_usage = getattr(case_runner, "last_model_usage", {})
    if not isinstance(model_usage, dict):
        model_usage = {}
    model_response_metadata = getattr(
        case_runner, "last_model_response_metadata", {}
    )
    if not isinstance(model_response_metadata, dict):
        model_response_metadata = {}
    agent_run_ledger = getattr(case_runner, "last_agent_run_ledger", {})
    if not isinstance(agent_run_ledger, dict):
        agent_run_ledger = {}
    agent_recovery = getattr(case_runner, "last_agent_recovery", {})
    if not isinstance(agent_recovery, dict):
        agent_recovery = {}
    context_handles = getattr(case_runner, "last_context_handles", [])
    if not isinstance(context_handles, list):
        context_handles = []
    expected_context_tool_ids = _context_tool_ids(workspace_root / project_id)
    context_evaluable_required = [
        tool_id for tool_id in required if tool_id in expected_context_tool_ids
    ]
    selected_context_tool_ids = {
        tool_id
        for handle in context_handles[:CONTEXT_HANDLE_EVAL_WIDTH]
        if isinstance(handle, dict)
        for tool_id in _string_list(
            (handle.get("scope_metadata") or {}).get("tool_ids")
            if isinstance(handle.get("scope_metadata"), dict)
            else None
        )
    }
    context_found_required = [
        tool_id
        for tool_id in context_evaluable_required
        if tool_id in selected_context_tool_ids
    ]
    context_top3_hit = (
        bool(context_found_required) if context_evaluable_required else None
    )
    context_top3_recall = (
        round(len(context_found_required) / len(context_evaluable_required), 4)
        if context_evaluable_required
        else None
    )
    context_top3_exact_match = (
        set(context_found_required) == set(context_evaluable_required)
        if context_evaluable_required
        else None
    )
    redacted_output = _redact(str(output))
    raw_model_answer = _redact(
        str(getattr(case_runner, "last_raw_model_output", "") or "")
    )
    raw_model_attempts = [
        _redact(str(item))
        for item in getattr(case_runner, "last_raw_model_outputs", [])
        if str(item).strip()
    ]
    finish_reason = str(model_response_metadata.get("finish_reason") or "").lower()
    recorded_verification = getattr(
        case_runner, "last_grounding_verification", {}
    )
    if (
        isinstance(recorded_verification, dict)
        and recorded_verification.get("output_disposition")
    ):
        grounding_verification = recorded_verification
    else:
        grounding_verification = _verify_answer_grounding(
            redacted_output,
            getattr(case_runner, "last_evidence_cards", []),
        )
    fail_closed = (
        isinstance(grounding_verification, dict)
        and grounding_verification.get("output_disposition") == "fail_closed"
    )
    user_visible_unsupported_claims = [
        str(claim)
        for claim in (
            (grounding_verification or {}).get("unsupported_claims") or []
        )
        if error is None
        and str(claim).strip()
        and str(claim).strip() in redacted_output
    ]
    answer_completed = (
        error is None
        and bool(redacted_output.strip())
        and finish_reason not in {"length", "max_tokens"}
        and not fail_closed
    )
    failure_category = _failure_category(
        error=error,
        required=required,
        missing_required=missing_required,
        extra_native=extra_native,
        answer_completed=answer_completed,
        invocations=invocations,
        grounding_verification=grounding_verification,
    )
    selected_tool_ids = _string_list(agent_run_ledger.get("selected_tool_ids"))
    tool_statuses_ok = all(
        _tool_status_succeeded(item.get("status")) for item in invocations
    )
    required_tools_matched = (
        required_tools_selected and error is None and tool_statuses_ok
    )
    case_passed = (
        required_tools_matched
        and answer_completed
        and isinstance(grounding_verification, dict)
        and bool(grounding_verification.get("passed"))
    )
    failure_class = _failure_class(
        failure_category=failure_category,
        required=required,
        selected_tool_ids=selected_tool_ids,
        missing_required=missing_required,
        invocations=invocations,
    )
    return {
        "case_id": case.case_id,
        "question": case.question,
        "notes": case.notes,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "latency_ms": latency_ms,
        "ok": error is None,
        "error": error,
        "model_native_tool_call_count": len(native_tool_ids),
        "model_native_tool_ids": native_tool_ids,
        "internal_composition_tool_call_count": len(
            internal_composition_tool_ids
        ),
        "internal_composition_tool_ids": internal_composition_tool_ids,
        "required_tool_ids": required,
        "missing_required_tool_ids": missing_required,
        "extra_native_tool_ids": extra_native,
        "tool_recall": tool_recall,
        "exact_required_tool_set_match": exact_required_tool_set_match,
        "required_tools_selected": required_tools_selected,
        "required_tools_matched": required_tools_matched,
        "case_passed": case_passed,
        "planner_expected_tool_ids": planned_tool_ids,
        "unexpected_native_tool_ids": unexpected_native,
        "tool_invocation_statuses": [
            {
                "tool_id": invocation.get("tool_id"),
                "status": invocation.get("status"),
                "answerability": invocation.get("answerability"),
                "result_count": invocation.get("result_count"),
                "source_status": invocation.get("source_status"),
            }
            for invocation in invocations
        ],
        "model_usage": {
            str(key): int(value)
            for key, value in model_usage.items()
            if isinstance(value, int)
        },
        "model_response_metadata": _public_model_response_metadata(
            model_response_metadata
        ),
        "agent_run_ledger": _eval_agent_run_ledger(
            agent_run_ledger,
            internal_composition_tool_count=len(internal_composition_tool_ids),
        ),
        "agent_recovery": agent_recovery,
        "context_handles": [
            _public_context_handle(item)
            for item in context_handles[:CONTEXT_HANDLE_EVAL_WIDTH]
            if isinstance(item, dict)
        ],
        "context_evaluable_required_tool_ids": context_evaluable_required,
        "context_found_required_tool_ids": context_found_required,
        "context_top3_hit": context_top3_hit,
        "context_top3_recall": context_top3_recall,
        "context_top3_exact_match": context_top3_exact_match,
        "grounding_verification": _public_grounding_verification(
            grounding_verification
        ),
        "user_visible_unsupported_claims": user_visible_unsupported_claims,
        "answer_grounded": (
            grounding_verification.get("passed")
            if grounding_verification is not None
            else None
        ),
        "failure_category": failure_category,
        "failure_class": failure_class,
        "answer_completed": answer_completed,
        "answer": redacted_output,
        "raw_model_answer": raw_model_answer,
        "raw_model_attempts": raw_model_attempts,
        "answer_preview": redacted_output.replace("\n", " ")[:700],
    }


def _sum_model_usage(samples: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for sample in samples:
        usage = sample.get("model_usage")
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals


def _eval_agent_run_ledger(
    ledger: dict[str, Any],
    *,
    internal_composition_tool_count: int,
) -> dict[str, Any]:
    public = _redacted_agent_run_ledger(ledger)
    selected_tool_ids = public.get("selected_tool_ids")
    if isinstance(selected_tool_ids, list):
        unique_ids = {str(tool_id) for tool_id in selected_tool_ids}
        internal_count = len(unique_ids & INTERNAL_COMPOSITION_TOOL_IDS)
        public["internal_composition_tool_schema_count"] = internal_count
        public["domain_tool_schema_count"] = len(unique_ids) - internal_count
    elif internal_composition_tool_count:
        public["internal_composition_tool_schema_count"] = 1
    return public


def _sum_agent_run_ledgers(samples: list[dict[str, Any]]) -> dict[str, int | float]:
    fields = (
        "request_count",
        "tool_call_count",
        "system_chars",
        "tool_schema_count",
        "tool_schema_chars",
        "user_history_chars",
        "tool_result_chars",
        "input_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
        "output_tokens",
        "estimated_cost",
        "cost_estimate_available",
        "retry_count",
        "repair_count",
    )
    totals: dict[str, int | float] = {field: 0 for field in fields}
    for sample in samples:
        ledger = sample.get("agent_run_ledger")
        if not isinstance(ledger, dict):
            continue
        for field in fields:
            value = ledger.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            totals[field] += value
    return totals


def _verify_answer_grounding(
    answer: str,
    raw_cards: object,
) -> dict[str, Any] | None:
    if not isinstance(raw_cards, list) or not raw_cards:
        return None
    cards: list[EvidenceCard] = []
    for item in raw_cards:
        try:
            cards.append(EvidenceCard.model_validate(item))
        except Exception:
            continue
    if not cards:
        return None
    return BoundedAgentRuntime.verify_synthesis(
        answer,
        evidence_cards=cards,
    ).model_dump(mode="json")


def _failure_category(
    *,
    error: dict[str, str] | None,
    required: list[str],
    missing_required: list[str],
    extra_native: list[str],
    answer_completed: bool,
    invocations: list[dict[str, Any]],
    grounding_verification: dict[str, Any] | None,
) -> str:
    if error is not None:
        error_type = str(error.get("type") or "")
        return "timeout" if "timeout" in error_type.casefold() else "transport_error"
    if required and not invocations:
        return "no_native_tool_calls"
    if missing_required:
        return "missing_required_tools"
    if extra_native:
        return "extra_tools_exact_miss"
    if any(not _tool_status_succeeded(item.get("status")) for item in invocations):
        return "tool_status_error"
    if (
        grounding_verification is not None
        and grounding_verification.get("output_disposition") == "fail_closed"
    ):
        return "answer_fail_closed"
    if not answer_completed:
        return "answer_incomplete"
    if grounding_verification is None:
        return "answer_grounding_unavailable"
    if grounding_verification is not None and not grounding_verification.get("passed"):
        return "answer_grounding_failed"
    return "ok"


def _tool_status_succeeded(value: object) -> bool:
    if value is None:
        return True
    return str(value).strip().casefold() in {"", "completed", "ok", "success"}


def _failure_class(
    *,
    failure_category: str,
    required: list[str],
    selected_tool_ids: list[str],
    missing_required: list[str],
    invocations: list[dict[str, Any]],
) -> str:
    if failure_category in {"transport_error", "timeout"}:
        return "provider_runtime_failure"
    if any(tool_id not in selected_tool_ids for tool_id in required):
        return "harness_tool_architecture_failure"
    if missing_required or failure_category == "no_native_tool_calls":
        return "model_tool_selection_failure"
    if any(
        item.get("missing_fields")
        or str(item.get("status")) in {"missing_input", "not_implemented", "failed"}
        for item in invocations
    ):
        return "evidence_insufficiency"
    if failure_category in {
        "answer_grounding_failed",
        "answer_grounding_unavailable",
        "answer_fail_closed",
    }:
        return "answer_grounding_failure"
    if failure_category == "tool_status_error":
        return "harness_tool_architecture_failure"
    if failure_category in {"answer_incomplete", "extra_tools_exact_miss"}:
        return "model_tool_selection_failure"
    return "ok"


def _redacted_agent_run_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "request_count",
        "tool_call_count",
        "system_chars",
        "tool_schema_count",
        "tool_schema_chars",
        "user_history_chars",
        "tool_result_chars",
        "input_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
        "output_tokens",
        "estimated_cost",
        "cost_estimate_available",
        "budget_remaining",
        "budget_stop_reason",
        "selected_tool_ids",
        "executed_tool_ids",
        "retry_count",
        "repair_count",
        "requests",
    }
    return {key: value for key, value in ledger.items() if key in allowed}


def _public_grounding_verification(
    verification: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(verification, dict):
        return None
    unsupported = verification.get("unsupported_claims")
    rejected = verification.get("rejected_draft_claims")
    invalid = verification.get("invalid_source_refs")
    repair_items = verification.get("repair_items")
    cited = verification.get("cited_source_refs")
    return {
        "passed": verification.get("passed") is True,
        "output_disposition": str(
            verification.get("output_disposition") or "unknown"
        ),
        "cited_source_refs": (
            [_redact(str(item)) for item in cited]
            if isinstance(cited, list)
            else []
        ),
        "invalid_source_ref_count": (
            len(invalid) if isinstance(invalid, list) else 0
        ),
        "unsupported_claims": [],
        "unsupported_claim_count": (
            int(verification.get("unsupported_claim_count") or 0)
            if isinstance(verification.get("unsupported_claim_count"), int)
            else (len(unsupported) if isinstance(unsupported, list) else 0)
        ),
        "rejected_draft_claim_count": (
            int(verification.get("rejected_draft_claim_count") or 0)
            if isinstance(verification.get("rejected_draft_claim_count"), int)
            else (len(rejected) if isinstance(rejected, list) else 0)
        ),
        "repair_item_count": (
            int(verification.get("repair_item_count") or 0)
            if isinstance(verification.get("repair_item_count"), int)
            else (len(repair_items) if isinstance(repair_items, list) else 0)
        ),
    }


def _public_context_handle(handle: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "context_id",
        "domain_id",
        "artifact_kind",
        "title",
        "freshness",
        "relevance_score",
        "estimated_tokens",
        "sensitivity",
        "candidate_only",
        "runtime_safety_truth",
    )
    return {key: handle.get(key) for key in allowed if key in handle}


def _public_model_response_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    allowed = {
        "context_full_recovery_count",
        "continuation_count",
        "external_limit",
        "finish_reason",
        "input_pack_estimated_tokens",
        "model_name",
        "provider",
        "provider_name",
        "semantic_stop",
        "semantic_completion",
        "streaming",
    }
    return {
        str(key): str(value)
        for key, value in metadata.items()
        if key in allowed and value is not None
    }


def _safe_eval_endpoint(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


@lru_cache(maxsize=16)
def _context_tool_ids(project_root: Path) -> frozenset[str]:
    try:
        registry = discover_scout_ai_context_sources(
            project_root,
            include_missing=True,
        )
    except (OSError, ValueError):
        return frozenset()
    return frozenset(
        tool_id
        for source in registry.sources
        if source.domain not in {"health", "team"}
        for tool_id in source.tool_ids
    )


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = _safe_filename(str(report.get("model") or "model"))
    json_path = output_dir / f"live_tool_selection_{safe_model}_{stamp}.json"
    md_path = output_dir / f"live_tool_selection_{safe_model}_{stamp}.md"
    safe_report = normalize_report_for_storage(report)
    json_path.write_text(
        json.dumps(safe_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_format_markdown(safe_report), encoding="utf-8")
    json_path.chmod(0o600)
    md_path.chmod(0o600)
    return json_path, md_path


def normalize_report_for_storage(report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized["artifact_sensitivity"] = "sensitive_local_eval"
    workspace_root = normalized.get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root:
        normalized["workspace_root"] = Path(workspace_root).name
    normalized["base_url"] = _safe_eval_endpoint(normalized.get("base_url"))

    samples: list[dict[str, Any]] = []
    for raw_sample in normalized.get("samples") or []:
        if not isinstance(raw_sample, dict):
            continue
        sample = dict(raw_sample)
        required = _string_list(sample.get("context_evaluable_required_tool_ids"))
        found = _string_list(sample.get("context_found_required_tool_ids"))
        sample["context_top3_hit"] = bool(found) if required else None
        sample["context_top3_recall"] = (
            round(len(set(found) & set(required)) / len(set(required)), 4)
            if required
            else None
        )
        sample["context_top3_exact_match"] = (
            set(found) == set(required) if required else None
        )
        sample["context_handles"] = [
            _public_context_handle(item)
            for item in sample.get("context_handles") or []
            if isinstance(item, dict)
        ][:CONTEXT_HANDLE_EVAL_WIDTH]
        sample["grounding_verification"] = _public_grounding_verification(
            sample.get("grounding_verification")
        )
        sample["model_response_metadata"] = _public_model_response_metadata(
            sample.get("model_response_metadata")
            if isinstance(sample.get("model_response_metadata"), dict)
            else {}
        )
        samples.append(sample)
    normalized["samples"] = samples

    context_evaluable = [
        sample for sample in samples if sample.get("context_top3_recall") is not None
    ]
    required_count = sum(
        len(set(_string_list(sample.get("context_evaluable_required_tool_ids"))))
        for sample in context_evaluable
    )
    found_count = sum(
        len(
            set(_string_list(sample.get("context_found_required_tool_ids")))
            & set(_string_list(sample.get("context_evaluable_required_tool_ids")))
        )
        for sample in context_evaluable
    )
    hit_count = sum(1 for sample in context_evaluable if sample["context_top3_hit"])
    exact_count = sum(
        1 for sample in context_evaluable if sample["context_top3_exact_match"]
    )
    normalized.update(
        {
            "context_top3_evaluable_count": len(context_evaluable),
            "context_top3_hit_count": hit_count,
            "context_top3_recall": (
                round(found_count / required_count, 4) if required_count else None
            ),
            "context_top3_macro_recall": (
                round(
                    sum(sample["context_top3_recall"] for sample in context_evaluable)
                    / len(context_evaluable),
                    4,
                )
                if context_evaluable
                else None
            ),
            "context_top3_any_hit_rate": (
                round(hit_count / len(context_evaluable), 4)
                if context_evaluable
                else None
            ),
            "context_top3_exact_match_count": exact_count,
            "context_top3_exact_match_rate": (
                round(exact_count / len(context_evaluable), 4)
                if context_evaluable
                else None
            ),
            "rejected_draft_claim_count": sum(
                int(
                    (sample.get("grounding_verification") or {}).get(
                        "rejected_draft_claim_count"
                    )
                    or 0
                )
                for sample in samples
            ),
        }
    )
    return _sanitize_eval_artifact(normalized)


def _format_markdown(report: dict[str, Any]) -> str:
    grounded_count = sum(
        1 for sample in report["samples"] if sample.get("answer_grounded") is True
    )
    rejected_draft_claim_count = sum(
        int(
            (sample.get("grounding_verification") or {}).get(
                "rejected_draft_claim_count"
            )
            or 0
        )
        for sample in report["samples"]
    )
    lines = [
        "# Scout AI Live Tool Selection Eval",
        "",
        f"- model: `{report.get('model')}`",
        f"- project: `{report.get('project_id')}`",
        f"- tool_selection_pass_rate: `{report.get('tool_selection_passed_count')}/{report.get('case_count')}`",
        f"- pass_rate: `{report.get('passed_count')}/{report.get('case_count')}`",
        f"- tool_recall_micro: `{report.get('tool_recall_micro')}`",
        f"- tool_recall_macro: `{report.get('tool_recall_macro')}`",
        f"- exact_set_match_rate: `{report.get('exact_set_match_rate')}`",
        f"- context_top3_recall: `{report.get('context_top3_recall')}`",
        f"- context_top3_macro_recall: `{report.get('context_top3_macro_recall')}`",
        f"- context_top3_exact_match_rate: `{report.get('context_top3_exact_match_rate')}`",
        f"- answer_completion_rate: `{report.get('answer_completion_rate')}`",
        f"- grounded_answers: `{grounded_count}/{report.get('case_count')}`",
        "- user_visible_unsupported_claim_count: "
        f"`{report.get('user_visible_unsupported_claim_count', 0)}`",
        f"- rejected_draft_claim_count: `{rejected_draft_claim_count}`",
        f"- model_usage_totals: `{json.dumps(report.get('model_usage_totals') or {}, sort_keys=True)}`",
        f"- agent_run_ledger_totals: `{json.dumps(report.get('agent_run_ledger_totals') or {}, sort_keys=True)}`",
        f"- failure_category_counts: `{json.dumps(report.get('failure_category_counts') or {}, sort_keys=True)}`",
        f"- failure_class_counts: `{json.dumps(report.get('failure_class_counts') or {}, sort_keys=True)}`",
        f"- assistant_api_pre_augmentation_used: `{report['scoring_policy']['assistant_api_pre_augmentation_used']}`",
        f"- counts_only_model_native_tool_calls: `{report['scoring_policy']['counts_only_model_native_tool_calls']}`",
        "",
        "| Case | Recall | Exact | Native tool calls | Missing required | Answer complete | Grounded | Failure category | Failure class | Requests | Input tokens |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for sample in report["samples"]:
        native_tools = ", ".join(sample["model_native_tool_ids"]) or "-"
        missing = ", ".join(sample["missing_required_tool_ids"]) or "-"
        ledger = sample.get("agent_run_ledger") or {}
        lines.append(
            f"| {sample['case_id']} | {sample['tool_recall']} | "
            f"{sample['exact_required_tool_set_match']} | `{native_tools}` | "
            f"`{missing}` | {sample['answer_completed']} | "
            f"{sample['answer_grounded']} | {sample['failure_category']} | "
            f"{sample['failure_class']} | {ledger.get('request_count', 0)} | "
            f"{ledger.get('input_tokens', 0)} |"
        )
    lines.append("")
    lines.append("## Answer Previews")
    for sample in report["samples"]:
        lines.extend(
            [
                "",
                f"### {sample['case_id']}",
                "",
                f"Question: {sample['question']}",
                "",
                sample["answer"] or "",
            ]
        )
        raw_model_answer = str(sample.get("raw_model_answer") or "")
        if raw_model_answer and raw_model_answer != sample["answer"]:
            lines.extend(
                [
                    "",
                    "Rejected/raw model draft (evaluation only):",
                    "",
                    raw_model_answer,
                ]
            )
    lines.append("")
    return "\n".join(lines)


def _redact(value: str) -> str:
    redacted = value
    for key, secret in os.environ.items():
        if not secret or not any(fragment in key.upper() for fragment in SECRET_NAME_FRAGMENTS):
            continue
        redacted = redacted.replace(secret, f"<redacted:{key}>")
    for pattern in SECRET_TEXT_PATTERNS:
        redacted = pattern.sub("<redacted:secret>", redacted)
    redacted = URL_PATTERN.sub(_redact_eval_url_match, redacted)
    redacted = ABSOLUTE_PATH_PATTERN.sub("<redacted:absolute-path>", redacted)
    return redacted


def _redact_eval_url_match(match: re.Match[str]) -> str:
    raw = match.group(0)
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return "<redacted:url>"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _sanitize_eval_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_eval_artifact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_eval_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_eval_artifact(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:80].strip("_") or "model"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--cases-file", type=Path, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--hardware-accelerator", default="none")
    parser.add_argument(
        "--disable-workspace-tools",
        action="store_true",
        help="Run the model without Pydantic AI workspace tool registration.",
    )
    parser.add_argument(
        "--api-key-env-var",
        default="OPENROUTER_API_KEY",
        help="Environment variable to read the model API key from.",
    )
    parser.add_argument(
        "--allow-missing-api-key",
        action="store_true",
        help="Allow local backends such as hailo_ollama to run without an API key.",
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--case-offset", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--max-context-chars", type=int, default=None)
    parser.add_argument("--model-max-tokens", type=int, default=None)
    parser.add_argument("--delay-between-cases-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)

    env_values = load_env_file(args.env_file)
    os.environ.update(env_values)
    api_key = os.environ.get(args.api_key_env_var)
    if not api_key and not args.allow_missing_api_key:
        raise SystemExit(f"{args.api_key_env_var} is missing; not running live eval")
    os.environ["SCOUT_PRETRIP_WORKSPACE_ROOT"] = str(args.workspace_root)
    base_cases = load_eval_cases(args.cases_file) if args.cases_file else WEATHER_GEO_CASES
    if args.case_offset < 0:
        raise SystemExit("--case-offset must be >= 0")
    offset_cases = base_cases[args.case_offset :]
    cases = offset_cases[: args.max_cases] if args.max_cases else offset_cases
    runner = PydanticAIEnvRunner(
        model_name=args.model,
        base_url=args.base_url,
        api_key=api_key,
        profile_name="live_tool_selection_eval",
        backend=args.backend,
        hardware_accelerator=args.hardware_accelerator,
        workspace_tools_enabled=not args.disable_workspace_tools,
        workspace_model_max_tokens=args.model_max_tokens,
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
    json_path, md_path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "status": "completed",
                "model": report["model"],
                "tool_selection_passed_count": report["tool_selection_passed_count"],
                "passed_count": report["passed_count"],
                "case_count": report["case_count"],
                "json_path": str(json_path),
                "markdown_path": str(md_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["failed_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
