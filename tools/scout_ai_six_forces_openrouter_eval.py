from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic_ai import Agent, Tool  # noqa: E402
from pydantic_ai.messages import ToolCallPart, ToolReturnPart  # noqa: E402

from assistant_pydantic_provider import (  # noqa: E402
    _serialize_pydantic_response_metadata,
    _serialize_pydantic_result_usage,
)
from pydantic_ai_runtime_compat import (  # noqa: E402
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_result_output,
)
from scout.agents.model_execution import ScoutModelExecutionAdapter  # noqa: E402
from scout.services.mser_pipeline import (  # noqa: E402
    MSERExecutionMode,
    MSERPipeline,
    compact_pipeline_context,
    decision_hint_for_force,
    mser_enforcement_errors,
)
from scout.services.mser_runtime_adapter import MSERRuntimeAdapter  # noqa: E402
from tools.scout_ai_live_tool_selection_eval import load_env_file  # noqa: E402
from tools.scout_ai_six_forces_aihat2_eval import (  # noqa: E402
    ARTIFACT_KIND as AIHAT_ARTIFACT_KIND,
    _write_summaries,
    apply_answer_quality_gate,
    assess_six_forces_answer_quality,
    build_three_axis_scorecard,
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

SYSTEM_PROMPT = """You are Scout AI's evidence-grounded answer synthesizer.
The deterministic Scout runtime exposes complete sanitized evidence cards through
Pydantic AI native function tools. Call every supplied evidence tool before the final
answer, use only its returned workspace and scenario evidence, preserve uncertainty,
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
    )


def normalize_openrouter_model(model: str) -> str:
    value = model.strip()
    return value if value.startswith("openrouter:") else f"openrouter:{value}"


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
    timeout_seconds: int,
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


def require_pydantic_ai_214() -> dict[str, str]:
    versions = runtime_package_versions()
    installed = versions.get("pydantic_ai_slim", "not-installed")
    if not installed.startswith("2.14."):
        raise RuntimeError(
            "This eval requires pydantic-ai-slim 2.14.x; "
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
            **pydantic_agent_runtime_kwargs(),
        )

    def __call__(
        self,
        *,
        endpoint: str,
        model: str,
        prompt: str,
        timeout_seconds: int,
        structured_json: bool,
    ) -> tuple[str, dict[str, Any]]:
        del endpoint, model, structured_json
        model_settings = build_openrouter_model_settings(
            max_tokens=self.max_tokens,
            timeout_seconds=timeout_seconds,
            thinking=self.thinking,
        )
        try:
            result = self._agent().run_sync(prompt, model_settings=model_settings)
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
        timeout_seconds: int,
        structured_json: bool,
        evidence_cards: list[dict[str, Any]],
        selected_tool_ids: list[str],
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
            result = self._agent(tools=tools).run_sync(
                prompt,
                model_settings=model_settings,
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


def _load_existing_results(results_path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not results_path.exists():
        return [], set()
    latest_by_id: dict[str, dict[str, Any]] = {}
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        latest_by_id[str(item["run_case_id"])] = item
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
            if item.get("mser_mode") not in {
                MSERExecutionMode.SHADOW.value,
                MSERExecutionMode.ENFORCE.value,
            }:
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


def revalidate_existing_result(
    row: dict[str, Any],
    *,
    run: dict[str, Any],
    mser_mode: str = "off",
    mser_runtime_adapter: MSERRuntimeAdapter | None = None,
) -> dict[str, Any]:
    """Reapply deterministic gates without making another model request."""

    resolved_mser_mode = MSERExecutionMode(mser_mode)
    output = row.get("model_output")
    compact = row.get("compact_evidence_stage") or {}
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
    verifier = apply_answer_quality_gate(
        verifier,
        quality,
        evidence_sufficient=not missing_tools and not blocking,
    )
    mser_trace: dict[str, Any] | None = None
    mser_answer_verification: dict[str, Any] | None = None
    mser_error: str | None = None
    final = None
    if resolved_mser_mode != MSERExecutionMode.OFF:
        try:
            reference_time = datetime.fromisoformat(
                str(run["scenario"]["observed_at"]).replace("Z", "+00:00")
            )
            pipeline = MSERPipeline(runtime_adapter=mser_runtime_adapter)
            initial = pipeline.prepare(
                question=str(run["question_text"]),
                scenario=run["scenario"],
                total_info=(
                    row.get("total_info_stage")
                    if isinstance(row.get("total_info_stage"), dict)
                    else None
                ),
                decision_hint=decision_hint_for_force(str(run["force_code"])),
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
            mser_answer_verification = pipeline.verify_model_output(
                state=final,
                output=output,
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
        "mser_mode": resolved_mser_mode.value,
        "mser_trace": mser_trace,
        "mser_error": mser_error,
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
        },
    }


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
    run_dir = (
        workspace
        / "outputs"
        / "evals"
        / f"six_forces_600_openrouter_deepseek_v4_flash_{run_id}"
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
        _load_existing_results(results_path) if args.resume else ([], set())
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
                revalidated = revalidate_existing_result(
                    row,
                    run=run,
                    mser_mode=resolved_mser_mode.value,
                    mser_runtime_adapter=mser_runtime_adapter,
                )
                updated_existing.append(revalidated)
                if any(
                    revalidated.get(field) != row.get(field)
                    for field in (
                        "mser_mode",
                        "mser_trace",
                        "mser_error",
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
        runtime_versions = require_pydantic_ai_214()
    current_time = utc_iso()
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
        "runtime_packages": runtime_versions,
        "max_tool_calls_per_attempt": 10,
        "max_model_requests_per_attempt": args.max_model_requests,
        "guided_retry_enabled": args.guided_retry,
        "workers": args.workers,
        "model_max_tokens": args.model_max_tokens,
        "thinking": thinking,
        "cloud_evidence_transport": "pydantic_native_tools_full_cards",
        "cloud_prompt_character_limit": None,
        "native_tool_calls_required": True,
        "mser_mode": getattr(args, "mser_mode", "shadow"),
        "weather_mode": "deterministic_weather_replay",
        "model_external_api_calls_made": model_calls_required,
        "preserved_model_outputs_from_prior_provider_run": bool(existing),
        "weather_external_api_calls_made": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "deterministic_revalidation_enabled": bool(args.revalidate_existing),
        "deterministic_revalidated_row_count": sum(
            bool(item.get("revalidation")) for item in existing
        ),
    }
    if args.resume:
        manifest["resumed_at"] = current_time
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
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
                max_model_requests=args.max_model_requests,
                guided_retry=args.guided_retry,
                model_adapter=build_openrouter_model_adapter(
                    model_caller(),
                    contextual_model_call=model_caller().call_with_context,
                ),
                mser_mode=getattr(args, "mser_mode", "shadow"),
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
                "mser_mode": getattr(args, "mser_mode", "shadow"),
                "mser_trace": None,
                "mser_error": (
                    f"{type(exc).__name__}:"
                    f"{redact_provider_error(str(exc), secrets=(args.api_key,))}"
                ),
                "mser_answer_verification": None,
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
                    f"[six-forces-openrouter] {index}/{len(runs)} {run['run_case_id']} "
                    f"verifier={result['verifier']['status']} "
                    f"identity={result['context_identity_check']['status']} "
                    f"requests={result['model_request_count']}",
                    file=sys.stderr,
                    flush=True,
                )
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
    if args.model_max_tokens is not None and args.model_max_tokens <= 0:
        parser.error("--model-max-tokens must be positive when provided")
    if args.revalidate_existing and not args.resume:
        parser.error("--revalidate-existing requires --resume")
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
