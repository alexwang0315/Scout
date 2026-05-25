from __future__ import annotations

from typing import Any, Callable

from admin_assistant_context import build_admin_assistant_context
from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery
from debug_assistant_context import RuntimeDebugEventLog, DebugMessageSource, build_debug_assistant_context
from hardware_readiness_assistant_context import build_hardware_readiness_assistant_context
from hardware_readiness_admin_view import load_hardware_readiness_fixture
from pretrip_assistant_context import build_pretrip_assistant_context


AssistantContextResolver = Callable[[ScoutAssistantQuery], list[AssistantSourceRef]]


def create_assistant_context_resolver(
    *,
    debug_event_log: RuntimeDebugEventLog | None = None,
    debug_message_source: DebugMessageSource | None = None,
    hardware_provider_health: list[dict[str, Any]] | None = None,
    hardware_interface_inventory: list[dict[str, Any]] | None = None,
    hardware_sample_replay_timeline: list[dict[str, Any]] | None = None,
    hardware_runtime_debug_events: list[dict[str, Any]] | None = None,
    hardware_mock_transport_queue: list[dict[str, Any]] | None = None,
) -> AssistantContextResolver:
    def resolve(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
        context = build_assistant_context(
            query,
            debug_event_log=debug_event_log,
            debug_message_source=debug_message_source,
            hardware_provider_health=hardware_provider_health,
            hardware_interface_inventory=hardware_interface_inventory,
            hardware_sample_replay_timeline=hardware_sample_replay_timeline,
            hardware_runtime_debug_events=hardware_runtime_debug_events,
            hardware_mock_transport_queue=hardware_mock_transport_queue,
        )
        if context is None:
            return query_source_refs(query)
        return assistant_source_refs_from_context(context, query=query)

    return resolve


def build_assistant_context(
    query: ScoutAssistantQuery,
    *,
    debug_event_log: RuntimeDebugEventLog | None = None,
    debug_message_source: DebugMessageSource | None = None,
    hardware_provider_health: list[dict[str, Any]] | None = None,
    hardware_interface_inventory: list[dict[str, Any]] | None = None,
    hardware_sample_replay_timeline: list[dict[str, Any]] | None = None,
    hardware_runtime_debug_events: list[dict[str, Any]] | None = None,
    hardware_mock_transport_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    try:
        if query.surface == AssistantSurface.DEBUG and debug_event_log is not None:
            return build_debug_assistant_context(
                debug_event_log,
                selected_event_id=query.selected_event_id,
                message_source=debug_message_source,
            )
        if query.surface == AssistantSurface.ADMIN:
            case_id = query.context_ref
            if case_id:
                return build_admin_assistant_context(
                    case_id,
                    selected_source_id=query.selected_artifact_id,
                )
        if query.surface == AssistantSurface.PRETRIP:
            project_id = query.project_id or query.context_ref
            if project_id:
                return build_pretrip_assistant_context(
                    project_id,
                    selected_source_id=query.selected_artifact_id,
                )
        if query.surface == AssistantSurface.HARDWARE_READINESS:
            if (
                hardware_interface_inventory is None
                and hardware_provider_health is None
                and hardware_sample_replay_timeline is None
                and hardware_runtime_debug_events is None
                and hardware_mock_transport_queue is None
            ):
                fixture = load_hardware_readiness_fixture()
                hardware_interface_inventory = fixture["interface_inventory"]
                hardware_provider_health = fixture["provider_health"]
                hardware_sample_replay_timeline = fixture["sample_replay_timeline"]
                hardware_runtime_debug_events = fixture["runtime_debug_events"]
                hardware_mock_transport_queue = fixture["mock_transport_queue"]
            return build_hardware_readiness_assistant_context(
                interface_inventory=hardware_interface_inventory,
                provider_health=hardware_provider_health,
                sample_replay_timeline=hardware_sample_replay_timeline,
                runtime_debug_events=hardware_runtime_debug_events,
                mock_transport_queue=hardware_mock_transport_queue,
                selected_provider_ref=query.selected_artifact_id or query.context_ref,
            )
    except KeyError:
        return None
    return None


def assistant_source_refs_from_context(
    context: dict[str, Any],
    *,
    query: ScoutAssistantQuery,
) -> list[AssistantSourceRef]:
    refs = [
        AssistantSourceRef(
            source_id=f"assistant_context.{context['surface']}",
            source_path=f"{context['surface']}_assistant_context",
            evidence_type="assistant_context_summary",
            selected=True,
            context_summary=_context_summary(context),
        )
    ]
    refs.extend(_source_refs(context.get("sources", []), query=query))
    return _dedupe_source_refs([*refs, *query_source_refs(query)])


def query_source_refs(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
    refs: list[AssistantSourceRef] = []
    if query.selected_event_id:
        refs.append(
            AssistantSourceRef(
                source_id=query.selected_event_id,
                evidence_type="runtime_debug_event",
                selected=True,
            )
        )
    if query.selected_artifact_id:
        refs.append(
            AssistantSourceRef(
                source_id=query.selected_artifact_id,
                evidence_type="admin_artifact",
                selected=True,
            )
        )
    if query.context_ref:
        refs.append(
            AssistantSourceRef(
                source_id=query.context_ref,
                evidence_type="assistant_context_ref",
                selected=True,
            )
        )
    if query.project_id:
        refs.append(
            AssistantSourceRef(
                source_id=query.project_id,
                evidence_type="pretrip_project",
                selected=True,
            )
        )
    return refs


def _source_refs(
    sources: list[dict[str, Any]],
    *,
    query: ScoutAssistantQuery,
) -> list[AssistantSourceRef]:
    selected_refs = {
        ref
        for ref in (
            query.selected_event_id,
            query.selected_artifact_id,
            query.context_ref,
            query.project_id,
        )
        if ref
    }
    refs: list[AssistantSourceRef] = []
    for source in sources:
        source_id = source.get("source_id")
        if not source_id:
            continue
        refs.append(
            AssistantSourceRef(
                source_id=str(source_id),
                source_path=source.get("source_path"),
                evidence_type=source.get("evidence_type"),
                selected=str(source_id) in selected_refs,
            )
        )
    return refs


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "surface": context.get("surface"),
        "read_only": context.get("read_only"),
        "bounded": context.get("bounded"),
        "auditable": context.get("auditable"),
        "summary": context.get("summary", {}),
        "limitations": context.get("limitations", []),
    }
    selected_event = context.get("selected_event")
    if selected_event is not None:
        summary["selected_event"] = selected_event
    selected_evidence = context.get("selected_evidence")
    if selected_evidence is not None:
        summary["selected_evidence"] = selected_evidence
    selected_provider = context.get("selected_provider")
    if selected_provider is not None:
        summary["selected_provider"] = selected_provider
    return summary


def _dedupe_source_refs(sources: list[AssistantSourceRef]) -> list[AssistantSourceRef]:
    seen: set[tuple[str, str | None, str | None]] = set()
    deduped: list[AssistantSourceRef] = []
    for source in sources:
        key = (source.source_id, source.source_path, source.evidence_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped
