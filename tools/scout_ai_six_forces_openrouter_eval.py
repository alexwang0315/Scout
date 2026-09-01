from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic_ai import Agent, Tool  # noqa: E402
from pydantic_ai.messages import ToolCallPart, ToolReturnPart  # noqa: E402

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from assistant_pydantic_provider import (  # noqa: E402
    _serialize_pydantic_response_metadata,
    _serialize_pydantic_result_usage,
)
from pydantic_ai_runtime_compat import (  # noqa: E402
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_native_research_capabilities_for_model,
    pydantic_result_output,
)
from scout.agents.model_execution import ScoutModelExecutionAdapter  # noqa: E402
from scout.agents.model_execution import (  # noqa: E402
    ModelRunCancellationRequested,
    ModelRunDeadlineExceeded,
)
from scout.nextgen.exp_praison_bridge import (  # noqa: E402
    ExpPraisonResearchBridge,
)
from scout.nextgen.intelligence_mcp import (  # noqa: E402
    IntelligenceMcpClientConfig,
    McpIntelligenceGateway,
)
from scout.services.mser_pipeline import (  # noqa: E402
    MSERExecutionMode,
    MSERPipeline,
    compact_pipeline_context,
    decision_hint_for_force,
    mser_enforcement_errors,
    task_contract_for_question,
)
from scout.services.mser_runtime_adapter import MSERRuntimeAdapter  # noqa: E402
from scout.services.mser_response_composer import (  # noqa: E402
    compose_conservative_gap_response,
)
from tools.scout_ai_aihat2_fallback_eval import run_tools  # noqa: E402
from tools.scout_ai_live_tool_selection_eval import load_env_file  # noqa: E402
from tools.scout_ai_six_forces_aihat2_eval import (  # noqa: E402
    ARTIFACT_KIND as AIHAT_ARTIFACT_KIND,
    _write_summaries,
    apply_answer_quality_gate,
    apply_structured_answer_obligation_recovery,
    assess_six_forces_answer_quality,
    build_three_axis_scorecard,
    enrich_compact_evidence_spatial_bindings,
    execute_run,
    expand_case_runs,
    quality_tool_results_for_gaps,
    runtime_package_versions,
    utc_iso,
    verify_model_output,
)

ARTIFACT_KIND = "scout_ai_six_forces_600_total_info_openrouter_eval"
ARTIFACT_VERSION = f"{ARTIFACT_KIND}.v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_WORKSPACE = Path("/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI")
DEFAULT_SCENARIO_ARTIFACT = Path("outputs/evals/scout_ai_six_forces_600_scenarios.json")
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
EVIDENCE_FULLTEXT_TOOL_ID = "pydantic_ai.tool.search_scout_evidence_fulltext.v0"

SYSTEM_PROMPT = """You are Scout AI's evidence-grounded answer synthesizer.
The deterministic Scout runtime exposes complete sanitized evidence cards through
Pydantic AI native function tools. Call every supplied evidence tool before the final
answer. WebSearch and WebFetch remain available for current public facts or explicit
evidence gaps, but may not replace workspace/scenario facts; fetch selected sources
before using them. Preserve uncertainty,
and return only the requested JSON. Never invent route facts, sensor state, weather
state, source references, or safety truth.
"""


def build_openrouter_model_adapter(
    model_call: Callable[..., tuple[str, dict[str, Any]]],
    *,
    contextual_model_call: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> ScoutModelExecutionAdapter:
    return ScoutModelExecutionAdapter(
        adapter_id="openrouter.pydantic_ai",
        profile="cloud",
        provider="openrouter",
        transport="pydantic_ai_openrouter",
        invoke=model_call,
        invoke_with_context=contextual_model_call,
        supports_run_controls=True,
    )


def normalize_openrouter_model(model: str) -> str:
    value = model.strip()
    return value if value.startswith("openrouter:") else f"openrouter:{value}"


def build_exp_praison_bridge(
    args: argparse.Namespace,
    *,
    workspace: Path,
) -> ExpPraisonResearchBridge | None:
    if not bool(getattr(args, "exp_praison_intelligence", False)):
        return None
    python = Path(getattr(args, "exp_praison_python", sys.executable)).expanduser()
    if not python.is_absolute():
        python = python.resolve()
    command = [
        str(python),
        "-m",
        "scout.nextgen.intelligence_mcp_server",
        "--mode",
        str(getattr(args, "exp_praison_mode", "praison-replay")),
    ]
    evidence_catalog = getattr(args, "exp_praison_evidence_catalog", None)
    if evidence_catalog is not None:
        catalog_path = Path(evidence_catalog).expanduser()
        if not catalog_path.is_absolute():
            catalog_path = workspace / catalog_path
        command.extend(("--evidence-catalog", str(catalog_path.resolve())))
    model_runtime_config = getattr(args, "exp_praison_model_runtime_config", None)
    if model_runtime_config is not None:
        config_path = Path(model_runtime_config).expanduser()
        if not config_path.is_absolute():
            config_path = workspace / config_path
        command.extend(("--model-runtime-config", str(config_path.resolve())))
    timeout_seconds = float(getattr(args, "exp_praison_timeout_seconds", 60))
    startup_timeout_seconds = float(
        getattr(args, "exp_praison_startup_timeout_seconds", 30)
    )
    mcp = McpIntelligenceGateway(
        IntelligenceMcpClientConfig(
            command=tuple(command),
            timeout_seconds=timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            pythonpath=os.pathsep.join((str(ROOT / "src"), str(ROOT))),
        )
    )
    return ExpPraisonResearchBridge(
        gateway=mcp,
        allowed_domains=tuple(
            getattr(args, "exp_praison_allowed_domain", ()) or ()
        ),
        blocked_domains=tuple(
            getattr(args, "exp_praison_blocked_domain", ()) or ()
        ),
        max_runtime_seconds=int(timeout_seconds),
        max_search_results=int(
            getattr(args, "exp_praison_max_search_results", 6)
        ),
        max_fetches=int(getattr(args, "exp_praison_max_fetches", 2)),
    )


def normalize_thinking_setting(value: str) -> bool | str | None:
    normalized = value.strip().lower()
    if normalized == "default":
        return None
    if normalized == "off":
        return False
    return normalized


def build_openrouter_model_settings(
    *,
    max_tokens: int | None,
    timeout_seconds: float | int,
    thinking: bool | str | None,
) -> dict[str, object]:
    settings: dict[str, object] = {"temperature": 0}
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    if thinking is not None:
        settings["thinking"] = thinking
    if timeout_seconds > 0:
        settings["timeout"] = float(timeout_seconds)
    return settings


async def _run_agent_with_controls(
    agent: Agent,
    prompt: str,
    *,
    model_settings: dict[str, object],
    run_timeout_seconds: float | None,
    cancellation_event: threading.Event | None,
) -> Any:
    if cancellation_event is not None and cancellation_event.is_set():
        raise ModelRunCancellationRequested(
            "model run was cancelled before Pydantic Agent execution"
        )
    task = asyncio.create_task(agent.run(prompt, model_settings=model_settings))
    loop = asyncio.get_running_loop()
    deadline = (
        loop.time() + run_timeout_seconds
        if run_timeout_seconds is not None
        else None
    )
    try:
        while True:
            if cancellation_event is not None and cancellation_event.is_set():
                raise ModelRunCancellationRequested(
                    "model run cancellation was requested during Pydantic Agent execution"
                )
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise ModelRunDeadlineExceeded(
                    "Pydantic Agent tool round exceeded the total run deadline"
                )
            wait_seconds = (
                remaining
                if cancellation_event is None
                else min(remaining, 0.05)
                if remaining is not None
                else 0.05
            )
            done, _ = await asyncio.wait((task,), timeout=wait_seconds)
            if task in done:
                return task.result()
    except (ModelRunCancellationRequested, ModelRunDeadlineExceeded):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise


def run_agent_with_controls(
    agent: Agent,
    prompt: str,
    *,
    model_settings: dict[str, object],
    run_timeout_seconds: float | None,
    cancellation_event: threading.Event | None,
) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _run_agent_with_controls(
                agent,
                prompt,
                model_settings=model_settings,
                run_timeout_seconds=run_timeout_seconds,
                cancellation_event=cancellation_event,
            )
        )
    raise RuntimeError("synchronous OpenRouter caller cannot run in an active event loop")


def redact_provider_error(message: str, *, secrets: tuple[str, ...] = ()) -> str:
    redacted = message
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(OPENROUTER_API_KEY\s*=\s*)[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted[:2000]


def require_pydantic_ai_232_or_newer() -> dict[str, str]:
    versions = runtime_package_versions()
    installed = versions.get("pydantic_ai_slim", "not-installed")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", installed)
    installed_release = (
        tuple(int(part) for part in match.groups()) if match is not None else ()
    )
    if installed_release < (2, 32, 0):
        raise RuntimeError(
            "This eval requires pydantic-ai-slim 2.32.0 or newer; "
            f"installed version is {installed}."
        )
    return versions


class OpenRouterModelCaller:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        max_tokens: int | None,
        thinking: bool | str | None,
    ) -> None:
        os.environ.setdefault("OPENAI_MAX_RETRIES", "0")
        self.model_name = normalize_openrouter_model(model_name)
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.chat_model = build_chat_model(model_name=self.model_name, api_key=api_key)

    def _agent(self, *, tools: list[Tool] | None = None) -> Agent:
        return Agent(
            self.chat_model,
            system_prompt=SYSTEM_PROMPT,
            tools=tools or (),
            capabilities=pydantic_native_research_capabilities_for_model(
                self.model_name
            ),
            **pydantic_agent_runtime_kwargs(),
        )

    def __call__(
        self,
        *,
        endpoint: str,
        model: str,
        prompt: str,
        timeout_seconds: float | int,
        structured_json: bool,
        run_timeout_seconds: float | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> tuple[str, dict[str, Any]]:
        del endpoint, model, structured_json
        model_settings = build_openrouter_model_settings(
            max_tokens=self.max_tokens,
            timeout_seconds=timeout_seconds,
            thinking=self.thinking,
        )
        try:
            result = run_agent_with_controls(
                self._agent(),
                prompt,
                model_settings=model_settings,
                run_timeout_seconds=run_timeout_seconds,
                cancellation_event=cancellation_event,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures belong in eval traces.
            return "", {
                "provider_error_type": type(exc).__name__,
                "provider_error": redact_provider_error(
                    str(exc), secrets=(self.api_key,)
                ),
            }
        return str(pydantic_result_output(result)), {
            "usage": _serialize_pydantic_result_usage(result),
            "response": _serialize_pydantic_response_metadata(result),
        }

    def call_with_context(
        self,
        *,
        endpoint: str,
        model: str,
        prompt: str,
        timeout_seconds: float | int,
        structured_json: bool,
        evidence_cards: list[dict[str, Any]],
        selected_tool_ids: list[str],
        run_timeout_seconds: float | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> tuple[str, dict[str, Any]]:
        del endpoint, model, structured_json
        tools, tool_name_to_id = build_native_evidence_tools(
            evidence_cards=evidence_cards,
            selected_tool_ids=selected_tool_ids,
        )
        model_settings = build_openrouter_model_settings(
            max_tokens=self.max_tokens,
            timeout_seconds=timeout_seconds,
            thinking=self.thinking,
        )
        try:
            result = run_agent_with_controls(
                self._agent(tools=tools),
                prompt,
                model_settings=model_settings,
                run_timeout_seconds=run_timeout_seconds,
                cancellation_event=cancellation_event,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures belong in eval traces.
            return "", {
                "provider_error_type": type(exc).__name__,
                "provider_error": redact_provider_error(
                    str(exc),
                    secrets=(self.api_key,),
                ),
                "native_tool_trace": empty_native_tool_trace(
                    offered_tool_ids=selected_tool_ids,
                ),
            }
        trace = native_tool_trace(
            result=result,
            tool_name_to_id=tool_name_to_id,
            offered_tool_ids=selected_tool_ids,
        )
        return str(pydantic_result_output(result)), {
            "usage": _serialize_pydantic_result_usage(result),
            "response": _serialize_pydantic_response_metadata(result),
            "native_tool_trace": trace,
        }


def native_tool_name(tool_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", tool_id).strip("_").lower()
    digest = hashlib.sha256(tool_id.encode("utf-8")).hexdigest()[:10]
    return f"read_{slug[:42]}_{digest}"[:64]


def build_native_evidence_tools(
    *,
    evidence_cards: list[dict[str, Any]],
    selected_tool_ids: list[str],
) -> tuple[list[Tool], dict[str, str]]:
    cards_by_id = {
        str(card.get("tool_id")): card for card in evidence_cards if card.get("tool_id")
    }
    ordered_ids = [tool_id for tool_id in selected_tool_ids if tool_id in cards_by_id]
    ordered_ids.extend(tool_id for tool_id in cards_by_id if tool_id not in ordered_ids)
    tools: list[Tool] = []
    tool_name_to_id: dict[str, str] = {}

    def reader_for(card: dict[str, Any]) -> Callable[[], dict[str, Any]]:
        def read_scout_evidence_card() -> dict[str, Any]:
            return card

        return read_scout_evidence_card

    for tool_id in ordered_ids:
        name = native_tool_name(tool_id)
        tools.append(
            Tool(
                reader_for(cards_by_id[tool_id]),
                name=name,
                description=(
                    "Read the complete sanitized Scout evidence card for "
                    f"{tool_id}. Call this tool before using this evidence."
                ),
                strict=True,
            )
        )
        tool_name_to_id[name] = tool_id
    return tools, tool_name_to_id


def empty_native_tool_trace(*, offered_tool_ids: list[str]) -> dict[str, Any]:
    return {
        "offered_tool_ids": list(offered_tool_ids),
        "called_tool_ids": [],
        "tool_call_count": 0,
        "tool_return_count": 0,
        "calls": [],
    }


def native_tool_trace(
    *,
    result: object,
    tool_name_to_id: dict[str, str],
    offered_tool_ids: list[str],
) -> dict[str, Any]:
    calls: list[dict[str, str]] = []
    return_count = 0
    messages_value = getattr(result, "all_messages", None)
    messages = messages_value() if callable(messages_value) else []
    for message in messages or []:
        for part in getattr(message, "parts", ()):
            if isinstance(part, ToolCallPart) and part.tool_name in tool_name_to_id:
                calls.append(
                    {
                        "tool_name": part.tool_name,
                        "tool_id": tool_name_to_id[part.tool_name],
                        "tool_call_id": part.tool_call_id,
                    }
                )
            elif isinstance(part, ToolReturnPart) and part.tool_name in tool_name_to_id:
                return_count += 1
    called_tool_ids = list(dict.fromkeys(call["tool_id"] for call in calls))
    return {
        "offered_tool_ids": list(offered_tool_ids),
        "called_tool_ids": called_tool_ids,
        "tool_call_count": len(calls),
        "tool_return_count": return_count,
        "calls": calls,
    }


def _load_existing_results(
    results_path: Path,
    *,
    include_failed: bool = False,
) -> tuple[list[dict[str, Any]], set[str]]:
    if not results_path.exists():
        return [], set()
    latest_by_id: dict[str, dict[str, Any]] = {}
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        latest_by_id[str(item["run_case_id"])] = item
    if include_failed:
        existing = list(latest_by_id.values())
    else:
        existing = [
            item
            for item in latest_by_id.values()
            if (item.get("verifier") or {}).get("status") == "pass"
            and (item.get("context_identity_check") or {}).get("status") == "pass"
            and item.get("failure_category") != "harness_failure"
        ]
    completed_ids = {str(item["run_case_id"]) for item in existing}
    return existing, completed_ids


def _write_mser_revalidation_integrity_report(
    *,
    results_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Prove that deterministic MSER replay preserved provider responses."""

    latest_by_id: dict[str, dict[str, Any]] = {}
    prior_provider_by_id: dict[str, dict[str, Any]] = {}
    line_count = 0
    with results_path.open(encoding="utf-8") as result_file:
        for line in result_file:
            if not line.strip():
                continue
            item = json.loads(line)
            run_case_id = str(item["run_case_id"])
            line_count += 1
            latest_by_id[run_case_id] = item
            if not item.get("revalidation"):
                prior_provider_by_id[run_case_id] = item

    preserved_fields = (
        "model_output",
        "raw_model_output",
        "model_metadata",
        "model_request_count",
    )
    mismatched_run_case_ids: list[str] = []
    compared_count = 0
    for run_case_id, latest in latest_by_id.items():
        prior = prior_provider_by_id.get(run_case_id)
        if prior is None:
            continue
        compared_count += 1
        if any(latest.get(field) != prior.get(field) for field in preserved_fields):
            mismatched_run_case_ids.append(run_case_id)

    report = {
        "artifact_kind": "scout_ai_mser_revalidation_integrity",
        "schema_version": "scout.ai.mser.revalidation_integrity.v0",
        "jsonl_line_count": line_count,
        "latest_run_count": len(latest_by_id),
        "prior_provider_run_count": len(prior_provider_by_id),
        "compared_run_count": compared_count,
        "preserved_model_payload_count": compared_count - len(mismatched_run_case_ids),
        "mismatched_run_case_ids": mismatched_run_case_ids,
        "model_call_performed_count": sum(
            bool((item.get("revalidation") or {}).get("model_call_performed"))
            for item in latest_by_id.values()
        ),
        "deterministic_tool_refresh_count": sum(
            bool(item.get("deterministic_evidence_refresh"))
            for item in latest_by_id.values()
        ),
        "deterministic_response_composition_count": sum(
            (item.get("deterministic_response_composition") or {}).get("status")
            == "composed"
            for item in latest_by_id.values()
        ),
        "mser_mode_counts": dict(
            sorted(
                Counter(
                    str(item.get("mser_mode") or "off")
                    for item in latest_by_id.values()
                ).items()
            )
        ),
        "mser_pipeline_error_count": sum(
            bool(item.get("mser_error")) for item in latest_by_id.values()
        ),
        "candidate_only_all": all(
            item.get("candidate_only") is True for item in latest_by_id.values()
        ),
        "runtime_safety_truth_all_false": all(
            item.get("runtime_safety_truth") is False for item in latest_by_id.values()
        ),
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def _is_legacy_ambiguous_fulltext_card(card: dict[str, Any]) -> bool:
    records = card.get("records")
    return (
        card.get("tool_id") == EVIDENCE_FULLTEXT_TOOL_ID
        and str(card.get("status") or "").casefold() == "completed"
        and not card.get("answerability")
        and not card.get("negative_search_receipt")
        and not str(card.get("field_answer") or "").strip()
        and (not records or records == [{}])
    )


def refresh_legacy_negative_search_evidence(
    row: dict[str, Any],
    *,
    run: dict[str, Any],
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Re-run only an ambiguous legacy full-text card; preserve model payloads."""

    tool_results = [dict(item) for item in row.get("tool_evidence_stage") or []]
    targets = [
        index
        for index, item in enumerate(tool_results)
        if _is_legacy_ambiguous_fulltext_card(item)
    ]
    if not targets:
        return dict(row), None

    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=str(run["question_text"]),
        project_id=str(run["scenario"]["project_id"]),
    )
    refreshed, missing_tools, missing_evidence = run_tools(
        query=query,
        project_root=project_root,
        tool_ids=[EVIDENCE_FULLTEXT_TOOL_ID],
        max_tools=1,
        synthetic_field_context=False,
    )
    if missing_tools or len(refreshed) != 1:
        return (
            dict(row),
            {
                "schema_version": "scout.ai.deterministic_evidence_refresh.v0",
                "tool_id": EVIDENCE_FULLTEXT_TOOL_ID,
                "status": "failed_closed",
                "reason": "deterministic_fulltext_refresh_unavailable",
                "missing_tools": missing_tools,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        )

    refreshed_card = refreshed[0]
    old_hash = hashlib.sha256(
        json.dumps(
            tool_results[targets[0]],
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    new_hash = hashlib.sha256(
        json.dumps(
            refreshed_card,
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    for index in targets:
        tool_results[index] = refreshed_card

    source_refs = list(row.get("source_refs") or [])
    source_refs.extend(
        str(item) for item in refreshed_card.get("source_refs") or [] if item
    )
    receipt = refreshed_card.get("negative_search_receipt")
    if isinstance(receipt, dict) and receipt.get("source_ref"):
        source_refs.append(str(receipt["source_ref"]))
    record = {
        "schema_version": "scout.ai.deterministic_evidence_refresh.v0",
        "tool_id": EVIDENCE_FULLTEXT_TOOL_ID,
        "status": "refreshed",
        "reason": "legacy_ambiguous_empty_fulltext_card",
        "old_card_sha256": old_hash,
        "new_card_sha256": new_hash,
        "negative_search_receipt_created": isinstance(receipt, dict),
        "missing_evidence": list(missing_evidence),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return (
        {
            **row,
            "tool_evidence_stage": tool_results,
            "source_refs": list(dict.fromkeys(source_refs)),
            "deterministic_evidence_refresh": record,
        },
        record,
    )


def revalidate_existing_result(
    row: dict[str, Any],
    *,
    run: dict[str, Any],
    mser_mode: str = "off",
    mser_runtime_adapter: MSERRuntimeAdapter | None = None,
    compose_conservative_gap_responses: bool = False,
) -> dict[str, Any]:
    """Reapply deterministic gates without making another model request."""

    resolved_mser_mode = MSERExecutionMode(mser_mode)
    output = row.get("model_output")
    compact = enrich_compact_evidence_spatial_bindings(
        compact_evidence=row.get("compact_evidence_stage") or {},
        tool_results=list(row.get("tool_evidence_stage") or []),
    )
    missing_tools = list(row.get("missing_tools") or [])
    blocking = list(row.get("blocking_missing_evidence") or [])
    quality_tools = quality_tool_results_for_gaps(
        tool_results=list(row.get("tool_evidence_stage") or []),
        blocking_missing_evidence=blocking,
        question_id=str(row.get("question_id") or ""),
    )
    quality = assess_six_forces_answer_quality(
        str((output or {}).get("answer") or ""),
        missing_tools=missing_tools,
        blocking_missing_evidence=blocking,
        tool_results=quality_tools,
    )
    verifier = verify_model_output(
        run=run,
        output=output,
        parse_error=None if output is not None else "missing_output",
        available_source_refs=set(str(item) for item in row.get("source_refs") or []),
        compact_evidence=compact,
    )
    mser_trace: dict[str, Any] | None = None
    mser_answer_verification: dict[str, Any] | None = None
    precomposition_mser_answer_verification: dict[str, Any] | None = None
    deterministic_response_composition: dict[str, Any] | None = None
    effective_response: dict[str, Any] | None = None
    mser_error: str | None = None
    final = None
    if resolved_mser_mode != MSERExecutionMode.OFF:
        try:
            reference_time = datetime.fromisoformat(
                str(run["scenario"]["observed_at"]).replace("Z", "+00:00")
            )
            pipeline = MSERPipeline(runtime_adapter=mser_runtime_adapter)
            decision_hint = decision_hint_for_force(str(run["force_code"]))
            task_contract = task_contract_for_question(
                str(run["question_text"]),
                decision_hint=decision_hint,
                answer_mode_hint=str(
                    (run.get("expected_decision_boundary") or {}).get(
                        "answer_mode"
                    )
                    or ""
                ),
                safety_relevant_hint=str(run["force_code"]) == "PER",
            )
            initial = pipeline.prepare(
                question=str(run["question_text"]),
                scenario=run["scenario"],
                total_info=(
                    row.get("total_info_stage")
                    if isinstance(row.get("total_info_stage"), dict)
                    else None
                ),
                decision_hint=decision_hint,
                task_contract=task_contract,
                now=reference_time,
            )
            final = initial
            payloads: tuple[Any, ...] = ()
            tool_results = row.get("tool_evidence_stage") or []
            if tool_results:
                final, payloads = pipeline.reproject_tools(
                    previous=initial,
                    tool_results=tool_results,
                    now=reference_time,
                )
            initial_verification = pipeline.verify_model_output(
                state=final,
                output=output,
                now=reference_time,
            )
            mser_answer_verification = initial_verification.model_dump(mode="json")
            if compose_conservative_gap_responses:
                composition = compose_conservative_gap_response(
                    state=final,
                    output=output,
                    verification=initial_verification,
                    base_contract_valid=(
                        verifier.get("status") == "pass"
                        and not verifier.get("errors")
                    ),
                )
                deterministic_response_composition = composition.model_dump(
                    mode="json"
                )
                if composition.status == "composed":
                    precomposition_mser_answer_verification = (
                        mser_answer_verification
                    )
                    effective_response = composition.effective_response.model_dump(
                        mode="json"
                    )
                    verifier = verify_model_output(
                        run=run,
                        output=effective_response,
                        parse_error=None,
                        available_source_refs=set(
                            str(item) for item in row.get("source_refs") or []
                        ),
                        compact_evidence=compact,
                    )
                    mser_answer_verification = pipeline.verify_model_output(
                        state=final,
                        output=effective_response,
                        now=reference_time,
                    ).model_dump(mode="json")
            mser_trace = {
                "schema_version": "scout.mser.eval_trace.v0",
                "mode": resolved_mser_mode.value,
                "initial": compact_pipeline_context(initial),
                "final": compact_pipeline_context(final),
                "state_snapshot_ids": [
                    initial.state_snapshot_id,
                    *(
                        [final.state_snapshot_id]
                        if final.state_snapshot_id != initial.state_snapshot_id
                        else []
                    ),
                ],
                "tool_signal_bindings": final.tool_signal_bindings,
                "reprojection_payloads": [
                    {
                        "tool_id": payload.tool_id,
                        "produces_dimensions": [
                            item.value for item in payload.produces_dimensions
                        ],
                        "freshness": payload.freshness,
                        "quality": payload.quality,
                        "missing_fields": list(payload.missing_fields),
                        "source_refs": list(payload.source_refs),
                        "reprojection_ready": payload.reprojection_ready,
                    }
                    for payload in payloads
                ],
                "selected_tool_ids": list(row.get("selected_tools") or []),
                "legacy_selected_tool_ids": list(
                    row.get("legacy_selected_tools") or row.get("selected_tools") or []
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        except Exception as exc:  # noqa: BLE001 - preserve row and classify the failure.
            mser_error = f"{type(exc).__name__}"
    enforcement_errors = mser_enforcement_errors(
        mode=resolved_mser_mode,
        state=final if resolved_mser_mode != MSERExecutionMode.OFF else None,
        verification=mser_answer_verification,
        pipeline_error=mser_error,
    )
    if enforcement_errors:
        verifier = {
            "status": "fail",
            "errors": [
                *list(verifier.get("errors") or []),
                *enforcement_errors,
            ],
        }
    quality = apply_structured_answer_obligation_recovery(
        quality,
        run=run,
        output=output,
        compact_evidence=compact,
        verifier=verifier,
    )
    verifier = apply_answer_quality_gate(
        verifier,
        quality,
        evidence_sufficient=not missing_tools and not blocking,
    )
    identity = row.get("context_identity_check") or {}
    scorecard = build_three_axis_scorecard(
        output=output,
        parse_error=None if output is not None else "missing_output",
        identity=identity,
        verifier=verifier,
        model_metadata=row.get("model_metadata") or {},
        native_tool_call_required=bool(row.get("native_tool_call_required")),
        available_source_refs=set(str(item) for item in row.get("source_refs") or []),
        completed_tools=list(row.get("completed_tools") or []),
        missing_tools=missing_tools,
        blocking_missing_evidence=blocking,
        tool_results=list(row.get("tool_evidence_stage") or []),
        question=str(row.get("question") or ""),
    )
    if mser_error and resolved_mser_mode == MSERExecutionMode.ENFORCE:
        failure_category = "mser_pipeline_error"
    elif output is None:
        failure_category = "model_output_schema_failure"
    elif missing_tools:
        failure_category = "missing_tool"
    elif blocking:
        failure_category = "missing_evidence"
    elif identity.get("status") != "pass":
        failure_category = "scenario_identity_failure"
    elif verifier.get("status") != "pass":
        failure_category = "answer_verification_failure"
    else:
        failure_category = None
    return {
        **row,
        "compact_evidence_stage": compact,
        "mser_mode": resolved_mser_mode.value,
        "mser_trace": mser_trace,
        "mser_error": mser_error,
        "precomposition_mser_answer_verification": (
            precomposition_mser_answer_verification
        ),
        "deterministic_response_composition": deterministic_response_composition,
        "effective_response": effective_response,
        "mser_answer_verification": mser_answer_verification,
        "verifier": verifier,
        "answer_quality_screen": quality,
        "three_axis_scorecard": scorecard,
        "failure_category": failure_category,
        "revalidation": {
            "at": utc_iso(),
            "model_call_performed": False,
            "preserved_model_output": True,
            "policy": "deterministic_answer_evidence_and_mser_gates",
            "conservative_response_composition": bool(
                deterministic_response_composition
                and deterministic_response_composition.get("status") == "composed"
            ),
        },
    }


def resolve_run_directory(
    *,
    workspace: Path,
    model: str,
    run_id: str,
    resume: bool,
) -> Path:
    model_slug = re.sub(
        r"[^a-z0-9]+",
        "_",
        model.removeprefix("openrouter:").lower(),
    ).strip("_")
    eval_root = workspace / "outputs" / "evals"
    canonical = eval_root / f"six_forces_600_openrouter_{model_slug}_{run_id}"
    if not resume or canonical.exists():
        return canonical

    legacy = eval_root / f"six_forces_600_openrouter_deepseek_v4_flash_{run_id}"
    manifest_path = legacy / "run_manifest.json"
    if not manifest_path.exists():
        return canonical
    try:
        legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return canonical
    legacy_model = normalize_openrouter_model(
        str(legacy_manifest.get("model") or "")
    )
    return legacy if legacy_model == model else canonical


def run_eval(args: argparse.Namespace) -> Path:
    runtime_versions = runtime_package_versions()
    thinking = normalize_thinking_setting(args.thinking)
    workspace = args.workspace.expanduser().resolve()
    scenario_path = workspace / args.scenario_artifact
    artifact = json.loads(scenario_path.read_text(encoding="utf-8"))
    runs = expand_case_runs(artifact)
    if args.question_id:
        wanted = set(args.question_id)
        runs = [item for item in runs if item["question_id"] in wanted]
    if args.offset:
        runs = runs[args.offset :]
    if args.max_runs is not None:
        runs = runs[: args.max_runs]

    model = normalize_openrouter_model(args.model)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = resolve_run_directory(
        workspace=workspace,
        model=model,
        run_id=run_id,
        resume=bool(args.resume),
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = run_dir / "scenario_artifact.snapshot.json"
    if not snapshot_path.exists():
        snapshot_path.write_bytes(scenario_path.read_bytes())

    results_path = run_dir / "per_case_results.jsonl"
    manifest_path = run_dir / "run_manifest.json"
    previous_manifest: dict[str, Any] = {}
    if args.resume and manifest_path.exists():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    existing, completed_ids = (
        _load_existing_results(
            results_path,
            include_failed=bool(args.revalidate_existing),
        )
        if args.resume
        else ([], set())
    )
    run_by_id = {str(item["run_case_id"]): item for item in runs}
    if args.revalidate_existing:
        resolved_mser_mode = MSERExecutionMode(
            getattr(args, "mser_mode", MSERExecutionMode.SHADOW.value)
        )
        mser_runtime_adapter = (
            MSERRuntimeAdapter()
            if resolved_mser_mode != MSERExecutionMode.OFF
            else None
        )
        updated_existing: list[dict[str, Any]] = []
        with results_path.open("a", encoding="utf-8") as revalidation_file:
            for index, row in enumerate(existing, start=1):
                run = run_by_id.get(str(row.get("run_case_id") or ""))
                if run is None:
                    updated_existing.append(row)
                    continue
                working_row = row
                refresh_record = None
                if getattr(args, "refresh_negative_search_receipts", False):
                    working_row, refresh_record = (
                        refresh_legacy_negative_search_evidence(
                            row,
                            run=run,
                            project_root=workspace,
                        )
                    )
                revalidated = revalidate_existing_result(
                    working_row,
                    run=run,
                    mser_mode=resolved_mser_mode.value,
                    mser_runtime_adapter=mser_runtime_adapter,
                    compose_conservative_gap_responses=bool(
                        getattr(args, "compose_conservative_gap_responses", False)
                    ),
                )
                if refresh_record is not None:
                    revalidated = {
                        **revalidated,
                        "revalidation": {
                            **dict(revalidated.get("revalidation") or {}),
                            "deterministic_tool_refresh": refresh_record,
                        },
                    }
                updated_existing.append(revalidated)
                if any(
                    revalidated.get(field) != row.get(field)
                    for field in (
                        "compact_evidence_stage",
                        "tool_evidence_stage",
                        "source_refs",
                        "deterministic_evidence_refresh",
                        "mser_mode",
                        "mser_trace",
                        "mser_error",
                        "precomposition_mser_answer_verification",
                        "deterministic_response_composition",
                        "effective_response",
                        "mser_answer_verification",
                        "verifier",
                        "answer_quality_screen",
                        "three_axis_scorecard",
                        "failure_category",
                    )
                ):
                    revalidation_file.write(
                        json.dumps(
                            revalidated,
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    revalidation_file.flush()
                if index % 25 == 0 or index == len(existing):
                    print(
                        "[six-forces-openrouter] "
                        f"revalidated={index}/{len(existing)} "
                        f"mser_mode={resolved_mser_mode.value}",
                        file=sys.stderr,
                        flush=True,
                    )
        existing = updated_existing
        completed_ids = {str(item["run_case_id"]) for item in existing}
    model_calls_required = any(
        str(item["run_case_id"]) not in completed_ids for item in runs
    )
    if model_calls_required:
        if not args.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is required because model calls are pending"
            )
        runtime_versions = require_pydantic_ai_232_or_newer()
    current_time = utc_iso()
    provider_runtime_versions = (
        previous_manifest.get("runtime_packages")
        if args.revalidate_existing and previous_manifest.get("runtime_packages")
        else runtime_versions
    )
    provider_model_calls_made = bool(
        model_calls_required
        or previous_manifest.get("model_external_api_calls_made", False)
    )
    manifest = {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "compatible_evidence_harness": AIHAT_ARTIFACT_KIND,
        "report_title": "Scout AI Six Forces 600 + Total Info OpenRouter Eval",
        "run_id": run_id,
        "started_at": previous_manifest.get("started_at") or current_time,
        "workspace": str(workspace),
        "scenario_artifact": str(scenario_path),
        "scenario_artifact_snapshot": str(snapshot_path),
        "scenario_artifact_sha256": hashlib.sha256(
            scenario_path.read_bytes()
        ).hexdigest(),
        "base_question_count": len({item["question_id"] for item in runs}),
        "model_run_count": len(runs),
        "model": model,
        "model_adapter_id": "openrouter.pydantic_ai",
        "model_profile": "cloud",
        "provider": "openrouter",
        "model_transport": "pydantic_ai_openrouter",
        "endpoint": OPENROUTER_ENDPOINT,
        "runtime_packages": provider_runtime_versions,
        "max_tool_calls_per_attempt": 10,
        "max_model_requests_per_attempt": args.max_model_requests,
        "total_run_timeout_seconds": float(
            getattr(args, "total_run_timeout_seconds", 0) or 0
        ),
        "guided_retry_enabled": args.guided_retry,
        "workers": args.workers,
        "model_max_tokens": args.model_max_tokens,
        "thinking": thinking,
        "cloud_evidence_transport": "pydantic_native_tools_full_cards",
        "cloud_prompt_character_limit": None,
        "native_tool_calls_required": True,
        "mser_mode": getattr(args, "mser_mode", "shadow"),
        "weather_mode": "deterministic_weather_replay",
        "model_external_api_calls_made": provider_model_calls_made,
        "preserved_model_outputs_from_prior_provider_run": bool(existing),
        "weather_external_api_calls_made": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "deterministic_revalidation_enabled": bool(args.revalidate_existing),
        "negative_search_receipt_refresh_enabled": bool(
            getattr(args, "refresh_negative_search_receipts", False)
        ),
        "conservative_gap_response_composition_enabled": bool(
            getattr(args, "compose_conservative_gap_responses", False)
        ),
        "experimental_praison_intelligence": {
            "enabled": bool(getattr(args, "exp_praison_intelligence", False)),
            "scope": "exp_deterministic_evidence_void_only",
            "mode": (
                str(getattr(args, "exp_praison_mode", "praison-replay"))
                if getattr(args, "exp_praison_intelligence", False)
                else None
            ),
            "transport": "stdio_mcp",
            "allowed_domains": list(
                getattr(args, "exp_praison_allowed_domain", ()) or ()
            ),
            "max_search_results": int(
                getattr(args, "exp_praison_max_search_results", 6)
            ),
            "max_fetches": int(getattr(args, "exp_praison_max_fetches", 2)),
            "silent_routing_allowed": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "deterministic_revalidated_row_count": sum(
            bool(item.get("revalidation")) for item in existing
        ),
    }
    if args.revalidate_existing:
        manifest["revalidation_runtime_packages"] = runtime_versions
        manifest["revalidation_external_model_calls_made"] = False
    if args.resume:
        manifest["resumed_at"] = current_time
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    experimental_intelligence_bridge = build_exp_praison_bridge(
        args,
        workspace=workspace,
    )

    thread_local = threading.local()

    def model_caller() -> OpenRouterModelCaller:
        caller = getattr(thread_local, "caller", None)
        if caller is None:
            caller = OpenRouterModelCaller(
                model_name=model,
                api_key=args.api_key,
                max_tokens=args.model_max_tokens,
                thinking=thinking,
            )
            thread_local.caller = caller
        return caller

    def evaluate_one(index: int, run: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        started = time.monotonic()
        try:
            result = execute_run(
                run=run,
                project_root=workspace,
                endpoint=OPENROUTER_ENDPOINT,
                model=model,
                timeout_seconds=args.timeout_seconds,
                total_run_timeout_seconds=(
                    float(getattr(args, "total_run_timeout_seconds", 0)) or None
                ),
                max_model_requests=args.max_model_requests,
                guided_retry=args.guided_retry,
                model_adapter=build_openrouter_model_adapter(
                    model_caller(),
                    contextual_model_call=model_caller().call_with_context,
                ),
                mser_mode=getattr(args, "mser_mode", "shadow"),
                compose_conservative_gap_responses=bool(
                    getattr(args, "compose_conservative_gap_responses", False)
                ),
                experimental_intelligence_bridge=experimental_intelligence_bridge,
            )
        except Exception as exc:  # noqa: BLE001 - continue the matrix with an audit record.
            result = {
                "question_id": run["question_id"],
                "case_id": run["base_case_id"],
                "run_case_id": run["run_case_id"],
                "question": run["question_text"],
                "force": run["force_code"],
                "scenario_id": run["scenario_id"],
                "variant_id": run["variant_id"],
                "model": model,
                "model_adapter_id": "openrouter.pydantic_ai",
                "model_profile": "cloud",
                "provider": "openrouter",
                "model_transport": "pydantic_ai_openrouter",
                "total_run_timeout_seconds": (
                    float(getattr(args, "total_run_timeout_seconds", 0)) or None
                ),
                "run_cancellation_receipt": None,
                "mser_mode": getattr(args, "mser_mode", "shadow"),
                "mser_trace": None,
                "mser_error": (
                    f"{type(exc).__name__}:"
                    f"{redact_provider_error(str(exc), secrets=(args.api_key,))}"
                ),
                "mser_answer_verification": None,
                "experimental_intelligence": None,
                "selected_tools": [],
                "legacy_selected_tools": [],
                "completed_tools": [],
                "missing_tools": [],
                "missing_evidence": [],
                "blocking_missing_evidence": [],
                "supplemental_missing_evidence": [],
                "evidence_sufficiency": "unknown",
                "context_identity_check": {
                    "status": "fail",
                    "errors": ["run_exception_before_identity_check"],
                },
                "model_output": None,
                "raw_model_output": "",
                "model_request_count": 0,
                "max_model_requests": args.max_model_requests,
                "guided_retry_enabled": args.guided_retry,
                "model_attempts": [],
                "semantic_stop_reason": "run_exception",
                "decision": None,
                "verifier": {"status": "fail", "errors": ["run_exception"]},
                "answer_quality_screen": {
                    "classification": "quality_fail",
                    "failure_reasons": ["run_exception"],
                },
                "three_axis_scorecard": {
                    "transport_schema": {"score": 0, "components": {}},
                    "safe_uncertainty": {"score": 0, "components": {}},
                    "semantic_answer_quality": {"score": 0, "components": {}},
                },
                "failure_category": "harness_failure",
                "source_refs": [],
                "source_hashes": {},
                "model_metadata": {
                    "run_error_type": type(exc).__name__,
                    "run_error": redact_provider_error(
                        str(exc), secrets=(args.api_key,)
                    ),
                },
                "duration_ms": int((time.monotonic() - started) * 1000),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        return index, result

    all_results = list(existing)
    pending = [
        (index, run)
        for index, run in enumerate(runs, start=1)
        if run["run_case_id"] not in completed_ids
    ]
    try:
        with results_path.open("a", encoding="utf-8") as result_file:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.workers
            ) as executor:
                futures = {
                    executor.submit(evaluate_one, index, run): (index, run)
                    for index, run in pending
                }
                for future in concurrent.futures.as_completed(futures):
                    index, run = futures[future]
                    _, result = future.result()
                    result_file.write(
                        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    result_file.flush()
                    all_results.append(result)
                    print(
                        f"[six-forces-openrouter] {index}/{len(runs)} "
                        f"{run['run_case_id']} "
                        f"verifier={result['verifier']['status']} "
                        f"identity={result['context_identity_check']['status']} "
                        f"requests={result['model_request_count']}",
                        file=sys.stderr,
                        flush=True,
                    )
    finally:
        if experimental_intelligence_bridge is not None:
            experimental_intelligence_bridge.close()
    _write_summaries(run_dir, manifest, all_results)
    if args.revalidate_existing:
        _write_mser_revalidation_integrity_report(
            results_path=results_path,
            output_path=run_dir / "mser_revalidation_integrity.json",
        )
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Scout Six-Forces 600 on Mac through OpenRouter."
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument(
        "--scenario-artifact", type=Path, default=DEFAULT_SCENARIO_ARTIFACT
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--api-key-env-var", default="OPENROUTER_API_KEY")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--total-run-timeout-seconds",
        type=float,
        default=0,
        help=(
            "Experimental total deadline across one Pydantic tool round and all "
            "guided retries; 0 keeps the existing unbounded run behavior."
        ),
    )
    parser.add_argument("--model-max-tokens", type=int, default=None)
    parser.add_argument(
        "--thinking",
        choices=("default", "off", "minimal", "low", "medium", "high", "xhigh"),
        default="default",
        help="Pydantic AI thinking setting recorded in the run manifest.",
    )
    parser.add_argument("--max-model-requests", type=int, default=10)
    parser.add_argument(
        "--mser-mode",
        choices=tuple(item.value for item in MSERExecutionMode),
        default=MSERExecutionMode.SHADOW.value,
    )
    parser.add_argument(
        "--guided-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--revalidate-existing",
        action="store_true",
        help="Reapply deterministic gates to resumed rows without model calls.",
    )
    parser.add_argument(
        "--refresh-negative-search-receipts",
        action="store_true",
        help=(
            "During deterministic revalidation, re-run only legacy ambiguous "
            "full-text cards to attach typed negative-search receipts."
        ),
    )
    parser.add_argument(
        "--compose-conservative-gap-responses",
        action="store_true",
        help=(
            "Experimental: during live execution or deterministic revalidation, "
            "compose a separate typed DELAY response only for a sole "
            "non-conservative MSER gap-decision violation."
        ),
    )
    parser.add_argument(
        "--exp-praison-intelligence",
        action="store_true",
        help=(
            "Experimental: call the MCP-isolated Praison Research specialist only "
            "for EXP questions with no deterministic field answer."
        ),
    )
    parser.add_argument(
        "--exp-praison-mode",
        choices=(
            "praison-replay",
            "praison-live-web",
            "praison-model-replay",
            "praison-openai-compatible",
        ),
        default="praison-replay",
    )
    parser.add_argument(
        "--exp-praison-python",
        type=Path,
        default=Path(sys.executable),
    )
    parser.add_argument("--exp-praison-evidence-catalog", type=Path)
    parser.add_argument("--exp-praison-model-runtime-config", type=Path)
    parser.add_argument(
        "--exp-praison-allowed-domain",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--exp-praison-blocked-domain",
        action="append",
        default=[],
    )
    parser.add_argument("--exp-praison-timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--exp-praison-startup-timeout-seconds",
        type=int,
        default=30,
    )
    parser.add_argument("--exp-praison-max-search-results", type=int, default=6)
    parser.add_argument("--exp-praison-max-fetches", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_runs is not None and args.max_runs <= 0:
        parser.error("--max-runs must be positive")
    if args.offset < 0:
        parser.error("--offset must be >= 0")
    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.max_model_requests < 10:
        parser.error("--max-model-requests must be >= 10")
    if args.total_run_timeout_seconds < 0:
        parser.error("--total-run-timeout-seconds must be >= 0")
    if args.model_max_tokens is not None and args.model_max_tokens <= 0:
        parser.error("--model-max-tokens must be positive when provided")
    if args.revalidate_existing and not args.resume:
        parser.error("--revalidate-existing requires --resume")
    if args.refresh_negative_search_receipts and not args.revalidate_existing:
        parser.error(
            "--refresh-negative-search-receipts requires --revalidate-existing"
        )
    if args.exp_praison_intelligence and args.revalidate_existing:
        parser.error(
            "--exp-praison-intelligence cannot acquire new evidence during "
            "--revalidate-existing"
        )
    if args.exp_praison_intelligence and not args.exp_praison_allowed_domain:
        parser.error(
            "--exp-praison-intelligence requires at least one "
            "--exp-praison-allowed-domain"
        )
    if args.exp_praison_timeout_seconds < 1:
        parser.error("--exp-praison-timeout-seconds must be positive")
    if args.exp_praison_startup_timeout_seconds < 1:
        parser.error("--exp-praison-startup-timeout-seconds must be positive")
    if args.exp_praison_max_search_results < 1:
        parser.error("--exp-praison-max-search-results must be positive")
    if not 1 <= args.exp_praison_max_fetches <= 9:
        parser.error("--exp-praison-max-fetches must be between 1 and 9")
    if args.exp_praison_max_fetches > args.exp_praison_max_search_results:
        parser.error(
            "--exp-praison-max-fetches cannot exceed "
            "--exp-praison-max-search-results"
        )
    if (
        args.exp_praison_mode == "praison-openai-compatible"
        and args.exp_praison_intelligence
        and args.exp_praison_model_runtime_config is None
    ):
        parser.error(
            "--exp-praison-mode praison-openai-compatible requires "
            "--exp-praison-model-runtime-config"
        )
    if (
        args.compose_conservative_gap_responses
        and args.mser_mode != MSERExecutionMode.ENFORCE.value
    ):
        parser.error(
            "--compose-conservative-gap-responses requires --mser-mode enforce"
        )
    os.environ.update(load_env_file(args.env_file))
    api_key = os.environ.get(args.api_key_env_var, "")
    if not api_key and not args.revalidate_existing:
        raise SystemExit(f"{args.api_key_env_var} is missing; not running live eval")
    args.api_key = api_key
    run_dir = run_eval(args)
    print(
        json.dumps({"status": "completed", "run_dir": str(run_dir)}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
