from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable
from fastapi import APIRouter, FastAPI

from assistant_context import AssistantContextResolver, query_source_refs
from assistant_workspace_total_info import (
    TOTAL_INFO_SOURCE_ID,
    build_workspace_total_info_source_ref,
    public_workspace_total_info_summary,
)
from assistant_models import (
    AssistantBoundary,
    AssistantObservability,
    AssistantRuntimePreference,
    AssistantSourceRef,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)
from assistant_provider import FailedAssistantProvider, MockAssistantProvider, ScoutAssistantProvider
from runtime_audit_ledger import FileRuntimeAuditLedger
from assistant_skill_router import (
    PRETRIP_FULL_WORKFLOW_SOURCE_ID,
    PRETRIP_TOOL_PLANNER_SKILL_ID,
    augment_pretrip_sources_with_tool_plan,
    build_pretrip_full_workflow_fallback_response,
    build_local_evidence_search_fallback_response,
    build_pretrip_tool_plan_fallback_response,
    resolve_assistant_query_with_skill,
)

AssistantQueryPreparation = Callable[
    [ScoutAssistantQuery],
    AssistantSourceRef | None,
]


def create_assistant_app(
    *,
    provider: ScoutAssistantProvider | None = None,
    context_resolver: AssistantContextResolver | None = None,
    provider_status: dict[str, object] | None = None,
    query_preparation: AssistantQueryPreparation | None = None,
    runtime_audit: FileRuntimeAuditLedger | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout Cross-Surface Assistant API")
    app.include_router(
        create_assistant_router(
            provider=provider,
            context_resolver=context_resolver,
            provider_status=provider_status,
            query_preparation=query_preparation,
            runtime_audit=runtime_audit,
        )
    )
    return app


def create_assistant_router(
    *,
    provider: ScoutAssistantProvider | None = None,
    context_resolver: AssistantContextResolver | None = None,
    provider_status: dict[str, object] | None = None,
    query_preparation: AssistantQueryPreparation | None = None,
    runtime_audit: FileRuntimeAuditLedger | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/assistant", tags=["assistant"])
    resolved_provider = provider or MockAssistantProvider()
    resolved_context = context_resolver or query_source_refs
    resolved_provider_status = provider_status or create_assistant_provider_status(
        provider=resolved_provider
    )

    @router.post("/query")
    def query_assistant(query: ScoutAssistantQuery) -> ScoutAssistantResponse:
        started_at = time.perf_counter()
        preparation_source = (
            query_preparation(query) if query_preparation is not None else None
        )
        sources = resolved_context(query)
        if preparation_source is not None:
            sources = [preparation_source, *sources]
        response = answer_assistant_query_safely(
            resolved_provider,
            query,
            sources=sources,
            started_at=started_at,
        )
        observability = response.observability
        if runtime_audit is not None and observability is not None:
            runtime_audit.record_agent_run(
                workspace_id=query.project_id,
                provider=observability.provider_class,
                model=(
                    observability.local_model_name
                    or observability.model_profile_used
                ),
                duration_ms=observability.latency_ms,
                safe_failure=observability.safe_failure,
                request_count=observability.request_count,
                tool_call_count=observability.tool_call_count,
                retry_count=observability.retry_count,
                input_tokens=observability.input_tokens,
                output_tokens=observability.output_tokens,
            )
        return response

    @router.get("/status")
    def assistant_status() -> dict[str, object]:
        status = dict(resolved_provider_status)
        status["startup_connection_status"] = getattr(
            resolved_provider,
            "startup_connection_status",
            status.get("startup_connection_status", "not_checked"),
        )
        return status

    return router


def answer_assistant_query_safely(
    provider: ScoutAssistantProvider,
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef] | None = None,
    started_at: float | None = None,
) -> ScoutAssistantResponse:
    _reset_provider_request_observability(provider)
    resolved_sources = _augment_sources_with_tool_registry_context(list(sources or []))
    resolved_sources = _augment_sources_with_workspace_total_info(
        query,
        sources=resolved_sources,
    )
    resolved_started_at = started_at if started_at is not None else time.perf_counter()
    try:
        skill_response = resolve_assistant_query_with_skill(
            query,
            sources=resolved_sources,
        )
        if skill_response is not None:
            return _with_observability(
                skill_response,
                provider=provider,
                sources=skill_response.sources,
                started_at=resolved_started_at,
                safe_failure=False,
            )
        if not _provider_uses_bounded_agent_runtime(provider):
            resolved_sources = _augment_pretrip_evidence_first_sources(
                query,
                sources=resolved_sources,
            )
            resolved_sources = _augment_pydantic_workspace_tool_sources(
                provider,
                query,
                sources=resolved_sources,
            )
        response = provider.answer(query, sources=resolved_sources)
        return _with_observability(
            response,
            provider=provider,
            sources=response.sources,
            started_at=resolved_started_at,
            safe_failure=isinstance(provider, FailedAssistantProvider),
        )
    except Exception as exc:
        fallback_sources = _augment_pretrip_evidence_first_sources(
            query,
            sources=resolved_sources,
        )
        fallback_sources = _augment_pydantic_workspace_tool_sources(
            provider,
            query,
            sources=fallback_sources,
        )
        workspace_tool_fallback = _workspace_tool_fallback_response(
            query,
            sources=fallback_sources,
            provider_error_type=type(exc).__name__,
        )
        if workspace_tool_fallback is not None:
            synthesized = _provider_grounded_synthesis_response(
                provider,
                query,
                workspace_tool_fallback,
                provider_error_type=type(exc).__name__,
            )
            if synthesized is not None:
                return _with_observability(
                    synthesized,
                    provider=provider,
                    sources=synthesized.sources,
                    started_at=resolved_started_at,
                    safe_failure=False,
                )
            workspace_tool_fallback = _mark_deterministic_fallback_only(
                workspace_tool_fallback,
                provider_error_type=type(exc).__name__,
            )
            return _with_observability(
                workspace_tool_fallback,
                provider=provider,
                sources=workspace_tool_fallback.sources,
                started_at=resolved_started_at,
                safe_failure=True,
            )
        full_workflow_fallback = build_pretrip_full_workflow_fallback_response(
            query,
            sources=resolved_sources,
            provider_error_type=type(exc).__name__,
        )
        if full_workflow_fallback is not None:
            return _with_observability(
                full_workflow_fallback,
                provider=provider,
                sources=full_workflow_fallback.sources,
                started_at=resolved_started_at,
                safe_failure=True,
            )
        tool_plan_fallback = build_pretrip_tool_plan_fallback_response(
            query,
            sources=resolved_sources,
            provider_error_type=type(exc).__name__,
        )
        if tool_plan_fallback is not None:
            return _with_observability(
                tool_plan_fallback,
                provider=provider,
                sources=tool_plan_fallback.sources,
                started_at=resolved_started_at,
                safe_failure=True,
            )
        fallback_response = build_local_evidence_search_fallback_response(
            query,
            sources=resolved_sources,
            provider_error_type=type(exc).__name__,
        )
        if fallback_response is not None:
            return _with_observability(
                fallback_response,
                provider=provider,
                sources=fallback_response.sources,
                started_at=resolved_started_at,
                safe_failure=True,
            )
        response = ScoutAssistantResponse(
            surface=query.surface,
            answer=(
                "Assistant provider failed safely. This response is still a "
                "read-only model interpretation and no Scout state was changed."
            ),
            sources=resolved_sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=[
                f"provider_error_type={type(exc).__name__}",
                "Provider failure was isolated from the source surface.",
                "No runtime, planning, outbound, review, or hardware state was changed.",
            ],
        )
        return _with_observability(
            response,
            provider=provider,
            sources=resolved_sources,
            started_at=resolved_started_at,
            safe_failure=True,
        )


def create_assistant_provider_status(
    *,
    provider: ScoutAssistantProvider,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    resolved_environ = environ or os.environ
    provider_name = resolved_environ.get("SCOUT_AI_ASSISTANT_PROVIDER", "mock").strip().lower()
    runtime_profile = resolved_environ.get("SCOUT_RUNTIME_PROFILE", "dev").strip() or "dev"
    status: dict[str, object] = {
        "read_only": True,
        "model_interpretation": True,
        "provider": provider_name,
        "provider_class": type(provider).__name__,
        "runtime_profile": runtime_profile,
        "startup_connection_status": getattr(provider, "startup_connection_status", "not_checked"),
        "config_path_configured": bool(resolved_environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")),
        "config_loaded": False,
        "cloud_only": False,
        "local_fallback_enabled": False,
        "local_fallback_mode": "disabled",
        "local_model_backend": "not_configured",
        "local_hardware_accelerator": "none",
        "ai_hat_plus_2_fallback_enabled": False,
        "ai_hat_plus_2_readiness_required": False,
        "ai_hat_plus_2_readiness_artifact": "tools/pi_ai_hat_plus_2_smoke.py",
        "manual_verification_required": False,
        "local_fallback_max_concurrency": 1,
        "readiness_starts_local_model": False,
        "local_model_listener_required_for_readiness": False,
        "status_model_switch_allowed": False,
        "token_values_exposed": False,
        "assistant_workflow": create_assistant_workflow_status(),
        "assistant_context_registry": create_assistant_context_registry_status(
            environ=resolved_environ
        ),
    }
    config_path = resolved_environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")
    if not config_path:
        return status

    try:
        from assistant_model_config import load_assistant_model_config

        model_config = load_assistant_model_config(config_path)
    except Exception as exc:
        status.update(
            {
                "config_error_type": type(exc).__name__,
                "config_loaded": False,
            }
        )
        return status

    local_fallback_enabled = model_config.fallback_to_local_on_error
    pi_field_profile = runtime_profile == "pi-field"
    ai_hat_plus_2_fallback = (
        model_config.local_model.hardware_accelerator
        == "raspberry_pi_ai_hat_plus_2_hailo10h"
    )
    if not local_fallback_enabled:
        local_fallback_mode = "disabled"
    elif pi_field_profile:
        local_fallback_mode = (
            "pi_field_ai_hat_plus_2_manual_opt_in"
            if ai_hat_plus_2_fallback
            else "pi_field_manual_opt_in"
        )
    else:
        local_fallback_mode = (
            "ai_hat_plus_2_configured_not_pi_field"
            if ai_hat_plus_2_fallback
            else "configured_not_pi_field"
        )

    status.update(
        {
            "config_loaded": True,
            "active_profile": model_config.active_profile,
            "cloud_model": model_config.cloud_model.model_name,
            "local_model": model_config.local_model.model_name,
            "local_model_backend": model_config.local_model.backend,
            "local_hardware_accelerator": model_config.local_model.hardware_accelerator,
            "timeout_seconds": model_config.timeout_seconds,
            "max_context_chars": model_config.max_context_chars,
            "connect_on_startup": model_config.connect_on_startup,
            "local_fallback_enabled": local_fallback_enabled,
            "local_fallback_fixed_schema": model_config.local_fallback_fixed_schema,
            "local_fallback_mode": local_fallback_mode,
            "ai_hat_plus_2_fallback_enabled": local_fallback_enabled
            and ai_hat_plus_2_fallback,
            "ai_hat_plus_2_readiness_required": local_fallback_enabled
            and ai_hat_plus_2_fallback
            and pi_field_profile,
            "manual_verification_required": local_fallback_enabled and pi_field_profile,
            "cloud_only": model_config.active_profile == "cloud"
            and not local_fallback_enabled,
        }
    )
    return status


def create_assistant_workflow_status(
    *,
    repo_root: object | None = None,
) -> dict[str, object]:
    try:
        from assistant_readiness_check import (
            REPO_ROOT,
            SCOUT_AI_WORKFLOW_MANIFEST_EXPECTATIONS,
            build_readiness_check,
        )

        root = Path(repo_root) if repo_root is not None else REPO_ROOT
        readiness = build_readiness_check(root)
        workflow_gate = readiness["checks"].get("scout_ai_workflow_gate", {})
        missing = list(workflow_gate.get("missing") or [])
        workflow_tool_ids = sorted(SCOUT_AI_WORKFLOW_MANIFEST_EXPECTATIONS.values())
        return {
            "source_id": "assistant_context.scout_ai_workflow",
            "available": bool(workflow_gate.get("ok")),
            "status": "ready" if workflow_gate.get("ok") else "needs_attention",
            "workflow_gate_ok": bool(workflow_gate.get("ok")),
            "overall_readiness_ok": bool(workflow_gate.get("ok")),
            "repository_readiness_ok": bool(readiness.get("ok")),
            "readiness_failed_checks": list(readiness.get("failed_checks") or []),
            "workflow_tool_ids": workflow_tool_ids,
            "workflow_tool_count": len(workflow_tool_ids),
            "checked_manifest_count": len(workflow_gate.get("checked_manifests") or []),
            "missing_count": len(missing),
            "missing": missing,
            "workflow_order": [
                "user_question",
                "context_registry_source_discovery",
                "registry_backed_tool_planner",
                "deterministic_read_only_tools",
                "evidence_collection",
                "evidence_backed_answer_synthesis",
                "sources_limitations_missing_evidence_safety_boundary",
                "assistant_workflow_eval_suite",
            ],
            "read_only": True,
            "runtime_safety_truth": False,
            "deterministic_tools_first": True,
            "model_synthesis_after_evidence": True,
            "candidate_evidence_is_runtime_truth": False,
            "live_safety_api_calls_allowed": False,
            "phase1_safety_mutation_allowed": False,
            "outbound_send_allowed": False,
            "hardware_control_allowed": False,
            "context_path_values_exposed": False,
            "credential_values_exposed": False,
        }
    except Exception as exc:  # Defensive: status must not depend on AI/model availability.
        return {
            "source_id": "assistant_context.scout_ai_workflow",
            "available": False,
            "status": "error",
            "error_type": type(exc).__name__,
            "read_only": True,
            "runtime_safety_truth": False,
            "deterministic_tools_first": True,
            "model_synthesis_after_evidence": True,
            "candidate_evidence_is_runtime_truth": False,
            "live_safety_api_calls_allowed": False,
            "phase1_safety_mutation_allowed": False,
            "outbound_send_allowed": False,
            "hardware_control_allowed": False,
            "context_path_values_exposed": False,
            "credential_values_exposed": False,
        }


def create_assistant_context_registry_status(
    *,
    environ: dict[str, str] | None = None,
    pretrip_workspace_root: object | None = None,
    live_navigation_evidence_dir: object | None = None,
) -> dict[str, object]:
    resolved_environ = environ or os.environ
    pretrip_configured = _configured_value(
        pretrip_workspace_root,
        resolved_environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT"),
    )
    live_navigation_configured = _configured_value(
        live_navigation_evidence_dir,
        resolved_environ.get("SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR"),
    )
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "pretrip_workspace_root_configured": pretrip_configured,
        "live_navigation_evidence_configured": live_navigation_configured,
        "live_navigation_evidence_adapter": (
            "sensorlogger_mqtt_jsonl" if live_navigation_configured else "not_configured"
        ),
        "context_path_values_exposed": False,
        "credential_values_exposed": False,
        "tool_registry": _assistant_tool_registry_status(),
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


def _assistant_tool_registry_status() -> dict[str, object]:
    try:
        from scout_ai_tool_contracts import tool_registry_output

        registry = tool_registry_output(include_not_implemented=True)
    except Exception as exc:  # Defensive: assistant status must remain safe.
        return {
            "source_id": "assistant_context.tool_registry",
            "available": False,
            "error_type": type(exc).__name__,
            "read_only": True,
            "runtime_safety_truth": False,
            "context_path_values_exposed": False,
            "credential_values_exposed": False,
        }

    missing_fields = registry.missing_evidence_fields_by_tool
    return {
        "source_id": "assistant_context.tool_registry",
        "available": True,
        "artifact_kind": registry.artifact_kind,
        "artifact_version": registry.artifact_version,
        "tool_count": registry.tool_count,
        "ready_current_tool_count": registry.ready_current_tool_count,
        "executable_tool_count": registry.executable_tool_count,
        "contract_only_tool_count": registry.contract_only_tool_count,
        "implementation_status_counts": registry.implementation_status_counts,
        "tool_ids_by_status": registry.tool_ids_by_status,
        "missing_evidence_tool_count": len(missing_fields),
        "missing_evidence_tool_ids": sorted(missing_fields),
        "missing_evidence_fields_by_tool": missing_fields,
        "read_only": registry.boundary.read_only,
        "runtime_safety_truth": registry.boundary.runtime_safety_truth,
        "context_path_values_exposed": False,
        "credential_values_exposed": False,
    }


def _augment_sources_with_tool_registry_context(
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    if any(source.source_id == "assistant_context.tool_registry" for source in sources):
        return sources
    return [*sources, _assistant_tool_registry_source_ref()]


def _augment_sources_with_workspace_total_info(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    project_root = _pretrip_workspace_project_root_from_env(query)
    source = build_workspace_total_info_source_ref(query, project_root=project_root)
    if source is None:
        return sources
    if any(existing.source_id == source.source_id for existing in sources):
        return sources
    return [source, *sources]


def _assistant_tool_registry_source_ref() -> AssistantSourceRef:
    return AssistantSourceRef(
        source_id="assistant_context.tool_registry",
        source_path="assistant_api.create_assistant_context_registry_status",
        evidence_type="assistant_context_tool_registry",
        selected=True,
        context_summary=_assistant_tool_registry_status(),
    )


def _augment_pretrip_evidence_first_sources(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    project_root = _pretrip_workspace_project_root_from_env(query)
    if project_root is None:
        return sources
    if any(source.source_id == PRETRIP_FULL_WORKFLOW_SOURCE_ID for source in sources):
        return sources
    try:
        return augment_pretrip_sources_with_tool_plan(
            query,
            sources=sources,
            project_root=project_root,
        )
    except Exception:
        return sources


def _augment_pydantic_workspace_tool_sources(
    provider: ScoutAssistantProvider,
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    if provider.__class__.__name__ != "PydanticAIAssistantProvider":
        return sources
    try:
        from assistant_pydantic_provider import (
            augment_sources_with_workspace_evidence_tool,
        )

        augmented_sources = sources
        project_root = _pretrip_workspace_project_root_from_env(query)
        if project_root is not None and not any(
            source.source_id == PRETRIP_TOOL_PLANNER_SKILL_ID
            for source in augmented_sources
        ):
            augmented_sources = augment_pretrip_sources_with_tool_plan(
                query,
                sources=augmented_sources,
                project_root=project_root,
            )
        return augment_sources_with_workspace_evidence_tool(
            query,
            sources=augmented_sources,
        )
    except Exception:
        return sources


def _pretrip_workspace_project_root_from_env(
    query: ScoutAssistantQuery,
) -> Path | None:
    if query.surface.value != "pretrip":
        return None
    project_id = query.project_id or query.context_ref
    workspace_root = os.environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT")
    if not project_id or not workspace_root:
        return None
    root = Path(workspace_root).expanduser().resolve()
    candidate = (root / project_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate == root:
        return None
    manifest = candidate / "project.json"
    if manifest.is_symlink():
        return None
    try:
        resolved_manifest = manifest.resolve(strict=True)
        resolved_manifest.relative_to(candidate)
    except (OSError, ValueError):
        return None
    if resolved_manifest.is_file():
        return candidate
    return None


def _workspace_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    try:
        from assistant_pydantic_provider import build_workspace_tool_fallback_response

        return build_workspace_tool_fallback_response(
            query,
            sources=sources,
            provider_error_type=provider_error_type,
        )
    except Exception:
        return None


def _provider_grounded_synthesis_response(
    provider: ScoutAssistantProvider,
    query: ScoutAssistantQuery,
    fallback_response: ScoutAssistantResponse,
    *,
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    if query.runtime_preference == AssistantRuntimePreference.AI_HAT_PLUS_2_FALLBACK:
        return None
    synthesizer = getattr(provider, "synthesize_grounded_answer", None)
    if not callable(synthesizer):
        return None
    try:
        synthesized = synthesizer(query, grounded_answer=fallback_response.answer)
    except Exception:
        return None
    if not str(synthesized or "").strip():
        return None
    return fallback_response.model_copy(
        update={
            "answer": (
                "Pydantic AI read-only model interpretation: "
                + str(synthesized).strip()
            ),
            "evidence_backed_answer": fallback_response.answer,
            "limitations": [
                *fallback_response.limitations,
                f"initial_provider_error_type={provider_error_type}",
                "grounded_model_synthesis_after_provider_error=passed",
                "Initial provider run failed, but Scout retried the cloud model with compact read-only tool evidence and used that model synthesis as the answer.",
            ],
        }
    )


def _mark_deterministic_fallback_only(
    response: ScoutAssistantResponse,
    *,
    provider_error_type: str,
) -> ScoutAssistantResponse:
    fallback_answer = response.answer
    return response.model_copy(
        update={
            "answer": (
                "Scout AI model answer unavailable：模型未成功回答；provider failed "
                "and grounded model synthesis did not produce a valid answer. "
                "deterministic read-only 工具摘要已保留在 evidence_backed_answer，"
                "不能算作模型答題品質成功。"
            ),
            "evidence_backed_answer": fallback_answer,
            "limitations": [
                *response.limitations,
                f"initial_provider_error_type={provider_error_type}",
                "deterministic_tool_fallback_only=true",
                "Provider run failed and grounded model synthesis did not produce a valid answer.",
                "Do not count this response as model answer quality success.",
            ],
        }
    )


def _with_observability(
    response: ScoutAssistantResponse,
    *,
    provider: ScoutAssistantProvider,
    sources: list[AssistantSourceRef],
    started_at: float,
    safe_failure: bool,
) -> ScoutAssistantResponse:
    latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if safe_failure:
        latency_class = "timeout_or_error"
    elif latency_ms >= 2000:
        latency_class = "slow"
    else:
        latency_class = "fast"
    context_size_chars = len(
        json.dumps(
            [source.model_dump(mode="json") for source in sources],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    model_profile_used = _provider_metadata(provider, "last_profile")
    run_ledger = _provider_runtime_value(provider, "last_agent_run_ledger")
    ledger = run_ledger if isinstance(run_ledger, dict) else {}
    raw_mser_trace = _provider_runtime_value(provider, "last_mser_trace")
    mser_trace = raw_mser_trace if isinstance(raw_mser_trace, dict) else {}
    raw_mser_verification = _provider_runtime_value(
        provider,
        "last_mser_answer_verification",
    )
    mser_verification = (
        raw_mser_verification
        if isinstance(raw_mser_verification, dict)
        else {}
    )
    mser_state = (
        mser_trace.get("final")
        if isinstance(mser_trace.get("final"), dict)
        else mser_trace.get("initial")
    )
    mser_state = mser_state if isinstance(mser_state, dict) else {}
    mser_packet = (
        mser_state.get("packet")
        if isinstance(mser_state.get("packet"), dict)
        else {}
    )
    mser_context = (
        mser_packet.get("compact_context")
        if isinstance(mser_packet.get("compact_context"), dict)
        else {}
    )
    mser_certificate = (
        mser_context.get("certificate")
        if isinstance(mser_context.get("certificate"), dict)
        else {}
    )
    mser_reasoning = (
        mser_state.get("reasoning")
        if isinstance(mser_state.get("reasoning"), dict)
        else {}
    )
    raw_cost_estimate_available = ledger.get("cost_estimate_available")
    cost_estimate_available = (
        raw_cost_estimate_available
        if isinstance(raw_cost_estimate_available, bool)
        else None
    )
    observability = AssistantObservability(
        provider_class=type(provider).__name__,
        source_count=len(sources),
        selected_source_count=sum(1 for source in sources if source.selected),
        context_size_chars=context_size_chars,
        latency_ms=latency_ms,
        latency_class=latency_class,
        safe_failure=safe_failure,
        model_profile_used=model_profile_used,
        failover_reason=_provider_metadata(provider, "last_failover_reason"),
        local_model_name=(
            _provider_metadata(provider, "local_model_name")
            if model_profile_used == "local"
            else None
        ),
        request_count=_optional_nonnegative_int(ledger.get("request_count")),
        tool_call_count=_optional_nonnegative_int(ledger.get("tool_call_count")),
        input_tokens=_optional_nonnegative_int(ledger.get("input_tokens")),
        cache_write_tokens=_optional_nonnegative_int(ledger.get("cache_write_tokens")),
        cache_read_tokens=_optional_nonnegative_int(ledger.get("cache_read_tokens")),
        output_tokens=_optional_nonnegative_int(ledger.get("output_tokens")),
        system_chars=_optional_nonnegative_int(ledger.get("system_chars")),
        tool_schema_count=_optional_nonnegative_int(ledger.get("tool_schema_count")),
        tool_schema_chars=_optional_nonnegative_int(ledger.get("tool_schema_chars")),
        user_history_chars=_optional_nonnegative_int(ledger.get("user_history_chars")),
        tool_result_chars=_optional_nonnegative_int(ledger.get("tool_result_chars")),
        estimated_cost=(
            None
            if cost_estimate_available is False
            else _optional_nonnegative_float(ledger.get("estimated_cost"))
        ),
        cost_estimate_available=cost_estimate_available,
        budget_remaining=(
            dict(ledger["budget_remaining"])
            if isinstance(ledger.get("budget_remaining"), dict)
            else None
        ),
        budget_stop_reason=(
            str(ledger["budget_stop_reason"])
            if ledger.get("budget_stop_reason")
            else None
        ),
        selected_tool_ids=_string_list(ledger.get("selected_tool_ids")),
        executed_tool_ids=_string_list(ledger.get("executed_tool_ids")),
        mser_mode=(
            str(mser_trace["mode"])
            if mser_trace.get("mode") in {"off", "shadow", "enforce"}
            else None
        ),
        mser_sufficiency_status=(
            str(mser_certificate["status"])
            if mser_certificate.get("status")
            else None
        ),
        mser_reasoning_disposition=(
            str(mser_reasoning["disposition"])
            if mser_reasoning.get("disposition")
            else None
        ),
        mser_selected_tool_ids=_string_list(
            mser_trace.get("selected_tool_ids")
        ),
        mser_answer_verification_passed=(
            bool(mser_verification["passed"])
            if isinstance(mser_verification.get("passed"), bool)
            else None
        ),
        retry_count=_optional_nonnegative_int(ledger.get("retry_count")),
        repair_count=_optional_nonnegative_int(ledger.get("repair_count")),
        request_ledger=(
            list(ledger["requests"])
            if isinstance(ledger.get("requests"), list)
            else []
        ),
    )
    public_sources = [
        source.model_copy(
            update={
                "context_summary": public_workspace_total_info_summary(
                    source.context_summary
                )
            }
        )
        if source.source_id == TOTAL_INFO_SOURCE_ID
        and isinstance(source.context_summary, dict)
        else source
        for source in response.sources
    ]
    return response.model_copy(
        update={"observability": observability, "sources": public_sources}
    )


def _provider_metadata(provider: ScoutAssistantProvider, name: str) -> str | None:
    value = _provider_runtime_value(provider, name)
    return str(value) if value is not None else None


def _reset_provider_request_observability(provider: ScoutAssistantProvider) -> None:
    defaults: dict[str, object | None] = {
        "last_profile": None,
        "last_error_type": None,
        "last_failover_reason": None,
        "last_model_usage": {},
        "last_model_response_metadata": {},
        "last_agent_run_ledger": {},
        "last_workspace_tool_invocations": [],
        "last_evidence_cards": [],
        "last_grounding_verification": {},
        "last_context_handles": [],
        "last_context_reads": [],
    }
    runner = getattr(provider, "runner", None)
    candidates = (
        provider,
        runner,
        getattr(runner, "primary_runner", None),
        getattr(runner, "fallback_runner", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        for name, default in defaults.items():
            if hasattr(candidate, name):
                setattr(
                    candidate,
                    name,
                    default.copy() if isinstance(default, (dict, list)) else default,
                )


def _provider_uses_bounded_agent_runtime(provider: ScoutAssistantProvider) -> bool:
    runner = getattr(provider, "runner", None)
    candidates = (
        provider,
        runner,
        getattr(runner, "primary_runner", None),
        getattr(runner, "fallback_runner", None),
    )
    return any(
        getattr(candidate, "bounded_agent_runtime_enabled", False) is True
        for candidate in candidates
        if candidate is not None
    )


def _provider_runtime_value(provider: ScoutAssistantProvider, name: str) -> object | None:
    runner = getattr(provider, "runner", None)
    candidates = [provider, runner]
    if runner is not None:
        last_profile = getattr(runner, "last_profile", None)
        primary_profile = getattr(runner, "primary_profile", "cloud")
        fallback_profile = getattr(runner, "fallback_profile", "local")
        if last_profile == primary_profile:
            candidates.append(getattr(runner, "primary_runner", None))
        elif last_profile == fallback_profile:
            candidates.append(getattr(runner, "fallback_runner", None))
        else:
            candidates.extend(
                [
                    getattr(runner, "primary_runner", None),
                    getattr(runner, "fallback_runner", None),
                ]
            )
    for candidate in candidates:
        if candidate is None:
            continue
        value = getattr(candidate, name, None)
        if value not in (None, {}, []):
            return value
    return None


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def _optional_nonnegative_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, float(value))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def create_assistant_provider_from_env(
    environ: dict[str, str] | None = None,
    *,
    pydantic_runner: object | None = None,
) -> ScoutAssistantProvider:
    resolved_environ = environ or os.environ
    provider_name = resolved_environ.get("SCOUT_AI_ASSISTANT_PROVIDER", "mock").strip().lower()
    if provider_name != "pydantic_ai":
        return MockAssistantProvider()

    from assistant_pydantic_provider import (
        DEFAULT_MAX_CONTEXT_CHARS,
        DEFAULT_TIMEOUT_SECONDS,
        PydanticAIAssistantProvider,
        PydanticAIEnvRunner,
        create_configured_pydantic_runner,
    )

    config_path = resolved_environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")
    workspace_root_value = resolved_environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT")
    pretrip_workspace_root = (
        Path(workspace_root_value).expanduser() if workspace_root_value else None
    )
    if config_path:
        from assistant_model_config import load_assistant_model_config

        try:
            model_config = load_assistant_model_config(config_path)
            runner = pydantic_runner or create_configured_pydantic_runner(
                model_config,
                environ=resolved_environ,
            )
            provider = PydanticAIAssistantProvider(
                runner=runner,
                timeout_seconds=model_config.effective_timeout_seconds(),
                max_context_chars=model_config.effective_max_context_chars(),
                pretrip_workspace_root=pretrip_workspace_root,
            )
            if model_config.connect_on_startup:
                _connect_provider_safely(provider)
            return provider
        except Exception as exc:
            return FailedAssistantProvider(
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    aggressive_construction_mode = _bool_from_env(
        resolved_environ,
        "SCOUT_AI_OS_AGGRESSIVE_CONSTRUCTION_MODE",
        default=True,
    )
    timeout_seconds = (
        None
        if aggressive_construction_mode
        else _int_from_env(
            resolved_environ,
            "SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
        )
    )
    max_context_chars = (
        None
        if aggressive_construction_mode
        else _int_from_env(
            resolved_environ,
            "SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS",
            DEFAULT_MAX_CONTEXT_CHARS,
        )
    )
    provider = PydanticAIAssistantProvider(
        runner=pydantic_runner or PydanticAIEnvRunner(),
        timeout_seconds=timeout_seconds,
        max_context_chars=max_context_chars,
        pretrip_workspace_root=pretrip_workspace_root,
    )
    return provider


def _int_from_env(
    environ: dict[str, str], key: str, default: int | None
) -> int | None:
    raw = environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _bool_from_env(
    environ: dict[str, str],
    key: str,
    *,
    default: bool,
) -> bool:
    raw = environ.get(key)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _configured_value(*values: object | None) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        return True
    return False


def _connect_provider_safely(provider: object) -> None:
    connector = getattr(provider, "connect", None)
    if not callable(connector):
        return
    try:
        connector()
    except Exception as exc:
        setattr(provider, "startup_connection_status", f"failed:{type(exc).__name__}")
