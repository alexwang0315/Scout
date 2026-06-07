from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from admin_assistant_context import build_admin_assistant_context
from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery
from debug_assistant_context import RuntimeDebugEventLog, DebugMessageSource, build_debug_assistant_context
from hardware_readiness_assistant_context import build_hardware_readiness_assistant_context
from hardware_readiness_admin_view import load_hardware_readiness_fixture
from pretrip_assistant_context import build_pretrip_assistant_context


AssistantContextResolver = Callable[[ScoutAssistantQuery], list[AssistantSourceRef]]

LIVE_NAVIGATION_SNAPSHOT_SOURCE_ID = "assistant_context.live_navigation_snapshot"
LIVE_NAVIGATION_SNAPSHOT_ALLOWED_FIELDS = (
    "observed_at",
    "lat",
    "lon",
    "elevation_m",
    "source",
    "hdop",
    "horizontal_accuracy_m",
    "fix_quality",
    "satellite_count",
    "max_cno_dbhz",
    "heading_deg",
    "course_deg",
    "speed_mps",
    "nearest_route_distance_m",
    "route_progress_m",
    "nearest_cp_id",
    "ins_dr_source",
    "confidence",
    "uncertainty_m",
    "last_anchor_at",
)


def create_assistant_context_resolver(
    *,
    debug_event_log: RuntimeDebugEventLog | None = None,
    debug_message_source: DebugMessageSource | None = None,
    pretrip_workspace_root: Path | str | None = None,
    live_navigation_evidence_dir: Path | str | None = None,
    live_navigation_route_path: Path | str | None = None,
    live_navigation_evidence_limit: int = 50,
    hardware_provider_health: list[dict[str, Any]] | None = None,
    hardware_interface_inventory: list[dict[str, Any]] | None = None,
    hardware_sample_replay_timeline: list[dict[str, Any]] | None = None,
    hardware_runtime_debug_events: list[dict[str, Any]] | None = None,
    hardware_mock_transport_queue: list[dict[str, Any]] | None = None,
) -> AssistantContextResolver:
    def resolve(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
        pretrip_project_root = _configured_pretrip_project_root(
            pretrip_workspace_root,
            query.project_id or query.context_ref,
        )
        context = build_assistant_context(
            query,
            debug_event_log=debug_event_log,
            debug_message_source=debug_message_source,
            pretrip_project_root=pretrip_project_root,
            hardware_provider_health=hardware_provider_health,
            hardware_interface_inventory=hardware_interface_inventory,
            hardware_sample_replay_timeline=hardware_sample_replay_timeline,
            hardware_runtime_debug_events=hardware_runtime_debug_events,
            hardware_mock_transport_queue=hardware_mock_transport_queue,
        )
        if context is None:
            sources = query_source_refs(query)
        else:
            sources = assistant_source_refs_from_context(context, query=query)
        return augment_sources_with_configured_live_navigation_evidence(
            query,
            sources=sources,
            evidence_dir=live_navigation_evidence_dir,
            project_root=pretrip_project_root,
            route_path=live_navigation_route_path,
            limit=live_navigation_evidence_limit,
        )

    return resolve


def build_assistant_context(
    query: ScoutAssistantQuery,
    *,
    debug_event_log: RuntimeDebugEventLog | None = None,
    debug_message_source: DebugMessageSource | None = None,
    pretrip_project_root: Path | str | None = None,
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
                    project_root=Path(pretrip_project_root)
                    if pretrip_project_root is not None
                    else None,
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
    live_navigation_source = _live_navigation_snapshot_source_ref(query)
    if live_navigation_source is not None:
        refs.append(live_navigation_source)
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


def augment_sources_with_configured_live_navigation_evidence(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    evidence_dir: Path | str | None,
    project_root: Path | str | None = None,
    route_path: Path | str | None = None,
    limit: int = 50,
) -> list[AssistantSourceRef]:
    if evidence_dir is None:
        return sources
    try:
        from scout_live_navigation_snapshot_evidence import (
            augment_sources_with_live_navigation_snapshot_evidence,
        )

        return _dedupe_source_refs(
            augment_sources_with_live_navigation_snapshot_evidence(
                query,
                sources=sources,
                evidence_dir=Path(evidence_dir).expanduser(),
                project_root=project_root,
                route_path=route_path,
                limit=limit,
            )
        )
    except Exception:
        return sources


def _configured_pretrip_project_root(
    pretrip_workspace_root: Path | str | None,
    project_id: str | None,
) -> Path | None:
    if pretrip_workspace_root is None:
        return None
    root = Path(pretrip_workspace_root).expanduser()
    if (root / "project.json").exists():
        return root
    if not project_id:
        return None
    candidate = root / project_id
    if (candidate / "project.json").exists():
        return candidate
    return None


def _live_navigation_snapshot_source_ref(
    query: ScoutAssistantQuery,
) -> AssistantSourceRef | None:
    snapshot = _bounded_live_navigation_snapshot(query.live_navigation_snapshot)
    if not snapshot:
        return None
    return AssistantSourceRef(
        source_id=LIVE_NAVIGATION_SNAPSHOT_SOURCE_ID,
        source_path="assistant_query.live_navigation_snapshot",
        evidence_type="live_navigation_snapshot",
        selected=True,
        context_summary={
            "live_navigation_snapshot": snapshot,
            "field_names": sorted(snapshot),
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
            "boundary": {
                "read_only": True,
                "runtime_safety_truth": False,
                "live_safety_api_calls_allowed": False,
                "phase1_safety_mutation_allowed": False,
                "remote_outbound_send_allowed": False,
                "hardware_control_allowed": False,
                "raw_payloads_embedded": False,
            },
        },
    )


def _bounded_live_navigation_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    bounded: dict[str, Any] = {}
    for field in LIVE_NAVIGATION_SNAPSHOT_ALLOWED_FIELDS:
        field_value = value.get(field)
        if _missing_live_navigation_value(field_value):
            continue
        bounded[field] = field_value
    return bounded


def _missing_live_navigation_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


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
