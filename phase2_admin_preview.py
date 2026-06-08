from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, TypeVar

from case_replay import score_case_replay
from phase2_brain_models import (
    Artifact,
    BrainNode,
    BrainNodeType,
    DecisionOptionSet,
    DerivedMeasurement,
    Mission,
    ObservedFact,
    RemoteStatusArtifact,
    SkillRunRecord,
)
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import (
    DEFAULT_OPTION_SET_REF,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_SEPARATION_EVENT_REF,
    DEFAULT_SKILL_RUN_REFS,
    MissingBrainReferenceError,
    build_case_replay_from_brain,
)
from phase2_refs import Phase2RefKind, classify_phase2_ref


BrainNodeT = TypeVar("BrainNodeT", bound=BrainNode)


SAFETY_GUARDRAILS: tuple[str, ...] = (
    "Preview evidence is for audit and review only.",
    "Refs may explain a decision window, but they do not guarantee a field outcome.",
    "Ambiguous or stale evidence must remain visible to the admin reviewer.",
)


@dataclass(frozen=True)
class AdminPhase2RemoteStatusPreview:
    id: str
    status: str
    message: str


@dataclass(frozen=True)
class AdminPhase2OptionSetPreview:
    id: str
    current_safety_level: str
    option_count: int
    option_ids: tuple[str, ...]
    option_labels: tuple[str, ...]


@dataclass(frozen=True)
class AdminPhase2SkillRunAuditPreview:
    id: str
    skill_id: str
    activation_decision: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]


@dataclass(frozen=True)
class AdminPhase2ResolvedRefPreview:
    ref: str
    ref_kind: str
    resolved: bool
    node_type: str | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class AdminPhase2ArtifactPreview:
    id: str
    artifact_kind: str
    uri: str
    media_type: str | None
    captured_at: str | None
    metadata_keys: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class AdminPhase1AdapterMeasurementPreview:
    id: str
    metric: str
    value: str | int | float | bool
    unit: str | None
    artifact_refs: tuple[str, ...]


@dataclass(frozen=True)
class AdminPhase1AdapterArtifactLinkPreview:
    artifact_ref: str
    fact_ids: tuple[str, ...]
    measurement_ids: tuple[str, ...]
    measurement_metrics: tuple[str, ...]
    evidence_count: int


@dataclass(frozen=True)
class AdminPhase1AdapterEvidencePreview:
    incident_id: str
    artifact_refs: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    measurement_metrics: tuple[AdminPhase1AdapterMeasurementPreview, ...]
    artifact_source_links: tuple[AdminPhase1AdapterArtifactLinkPreview, ...]
    artifact_count: int
    fact_count: int
    measurement_count: int


@dataclass(frozen=True)
class AdminPhase2ReadOnlyPreview:
    mission_id: str
    remote_status: AdminPhase2RemoteStatusPreview
    option_sets: tuple[AdminPhase2OptionSetPreview, ...]
    skill_run_audit_ids: tuple[str, ...]
    skill_run_audits: tuple[AdminPhase2SkillRunAuditPreview, ...]
    case_verdict_level: str
    artifact_refs: tuple[str, ...]
    evidence_refs: tuple[AdminPhase2ResolvedRefPreview, ...]
    artifact_previews: tuple[AdminPhase2ArtifactPreview, ...]
    phase1_adapter_evidence: tuple[AdminPhase1AdapterEvidencePreview, ...]
    safety_guardrails: tuple[str, ...]

    @property
    def option_set_ids(self) -> tuple[str, ...]:
        return tuple(option_set.id for option_set in self.option_sets)


def build_phase2_admin_preview(
    store: BrainFileStore,
    *,
    mission_id: str | None = None,
    remote_status_ref: str = DEFAULT_REMOTE_STATUS_REF,
    option_set_refs: Iterable[str] = (DEFAULT_OPTION_SET_REF,),
    separation_event_ref: str = DEFAULT_SEPARATION_EVENT_REF,
    skill_run_refs: Iterable[str] = DEFAULT_SKILL_RUN_REFS,
    case_skill_run_refs: Iterable[str] = DEFAULT_SKILL_RUN_REFS,
) -> AdminPhase2ReadOnlyPreview:
    """Build the Phase 2 admin preview from persisted Brain nodes only."""

    remote_status = _load_required(store, remote_status_ref, RemoteStatusArtifact)
    mission = _mission_for_preview(store, mission_id=mission_id, remote_status=remote_status)
    option_sets = tuple(
        _option_set_preview(_load_required(store, option_set_ref, DecisionOptionSet))
        for option_set_ref in option_set_refs
    )
    skill_runs = tuple(
        _load_required(store, skill_run_ref, SkillRunRecord) for skill_run_ref in skill_run_refs
    )
    case_skill_runs = tuple(
        _load_required(store, skill_run_ref, SkillRunRecord) for skill_run_ref in case_skill_run_refs
    )
    case = build_case_replay_from_brain(
        store,
        remote_status_ref=remote_status.id,
        option_set_ref=option_sets[0].id,
        separation_event_ref=separation_event_ref,
        skill_run_refs=[skill_run.id for skill_run in case_skill_runs],
    )
    verdict = score_case_replay(case)
    evidence_ref_sources = _evidence_ref_sources(
        remote_status=remote_status,
        option_set_refs=[option_set.id for option_set in option_sets],
        skill_runs=skill_runs,
        separation_event_ref=separation_event_ref,
        case=case,
    )
    artifact_refs = _artifact_refs_for_preview(
        store=store,
        remote_status=remote_status,
        option_set_refs=[option_set.id for option_set in option_sets],
        skill_runs=skill_runs,
        case_artifact_refs=[
            *(
                artifact_ref
                for checkpoint in case.timeline
                for artifact_ref in checkpoint.artifact_refs
            ),
            *(
                artifact_ref
                for evidence in case.post_incident_evidence
                for artifact_ref in evidence.artifact_refs
            ),
        ],
    )

    return AdminPhase2ReadOnlyPreview(
        mission_id=mission.id,
        remote_status=AdminPhase2RemoteStatusPreview(
            id=remote_status.id,
            status=remote_status.status,
            message=remote_status.message,
        ),
        option_sets=option_sets,
        skill_run_audit_ids=tuple(skill_run.id for skill_run in skill_runs),
        skill_run_audits=tuple(_skill_run_audit(skill_run) for skill_run in skill_runs),
        case_verdict_level=verdict.level.value,
        artifact_refs=artifact_refs,
        evidence_refs=_resolved_refs_for_preview(store, evidence_ref_sources),
        artifact_previews=_artifact_previews_for_preview(
            store,
            artifact_refs=artifact_refs,
            evidence_ref_sources=evidence_ref_sources,
        ),
        phase1_adapter_evidence=_phase1_adapter_evidence_for_preview(store),
        safety_guardrails=SAFETY_GUARDRAILS,
    )


def _mission_for_preview(
    store: BrainFileStore,
    *,
    mission_id: str | None,
    remote_status: RemoteStatusArtifact,
) -> Mission:
    selected_mission_id = mission_id or remote_status.mission_id
    if selected_mission_id is not None:
        return _load_required(store, selected_mission_id, Mission)

    missions = store.list_nodes(BrainNodeType.MISSION)
    if len(missions) != 1:
        raise MissingBrainReferenceError(
            f"preview requires one Mission when remote status has no mission_id, found {len(missions)}"
        )
    mission = missions[0]
    if not isinstance(mission, Mission):
        raise MissingBrainReferenceError(f"required Brain ref {mission.id} is not a Mission")
    return mission


def _option_set_preview(option_set: DecisionOptionSet) -> AdminPhase2OptionSetPreview:
    return AdminPhase2OptionSetPreview(
        id=option_set.id,
        current_safety_level=option_set.current_safety_level,
        option_count=len(option_set.options),
        option_ids=tuple(option.id for option in option_set.options),
        option_labels=tuple(option.label for option in option_set.options),
    )


def _skill_run_audit(skill_run: SkillRunRecord) -> AdminPhase2SkillRunAuditPreview:
    return AdminPhase2SkillRunAuditPreview(
        id=skill_run.id,
        skill_id=skill_run.skill_id,
        activation_decision=skill_run.activation_decision,
        input_refs=tuple(skill_run.input_refs),
        output_refs=tuple(skill_run.output_refs),
    )


def _artifact_refs_for_preview(
    *,
    store: BrainFileStore,
    remote_status: RemoteStatusArtifact,
    option_set_refs: list[str],
    skill_runs: tuple[SkillRunRecord, ...],
    case_artifact_refs: list[str],
) -> tuple[str, ...]:
    refs: list[str] = []
    refs.extend(remote_status.artifact_refs)
    refs.extend(case_artifact_refs)

    for option_set_ref in option_set_refs:
        option_set = _load_required(store, option_set_ref, DecisionOptionSet)
        refs.extend(option_set.artifact_refs)

    for skill_run in skill_runs:
        refs.extend(skill_run.artifact_refs)
        refs.extend(
            ref
            for ref in [*skill_run.input_refs, *skill_run.output_refs]
            if classify_phase2_ref(ref) == Phase2RefKind.ARTIFACT
        )

    return tuple(ref for ref in _dedupe(refs) if _is_artifact_ref(store, ref))


def _evidence_ref_sources(
    *,
    remote_status: RemoteStatusArtifact,
    option_set_refs: list[str],
    skill_runs: tuple[SkillRunRecord, ...],
    separation_event_ref: str,
    case: Any,
) -> dict[str, tuple[str, ...]]:
    sources: dict[str, list[str]] = {}

    _record_ref_source(sources, remote_status.id, "preview.remote_status")
    for artifact_ref in remote_status.artifact_refs:
        _record_ref_source(sources, artifact_ref, remote_status.id)

    for option_set_ref in option_set_refs:
        _record_ref_source(sources, option_set_ref, "preview.option_sets")

    _record_ref_source(sources, separation_event_ref, "preview.case_replay")

    for skill_run in skill_runs:
        _record_ref_source(sources, skill_run.id, "preview.skill_run_audits")
        for ref in [*skill_run.input_refs, *skill_run.output_refs, *skill_run.artifact_refs]:
            _record_ref_source(sources, ref, skill_run.id)

    for checkpoint in case.timeline:
        checkpoint_source = f"case.timeline.{checkpoint.label}"
        for ref in [
            *checkpoint.evidence_refs,
            *checkpoint.artifact_refs,
            checkpoint.remote_status_ref,
            checkpoint.option_set_ref,
        ]:
            if ref is not None:
                _record_ref_source(sources, ref, checkpoint_source)

    for evidence in case.post_incident_evidence:
        for artifact_ref in evidence.artifact_refs:
            _record_ref_source(sources, artifact_ref, evidence.id)

    return {ref: tuple(source_ids) for ref, source_ids in sources.items()}


def _resolved_refs_for_preview(
    store: BrainFileStore,
    evidence_ref_sources: dict[str, tuple[str, ...]],
) -> tuple[AdminPhase2ResolvedRefPreview, ...]:
    resolved_refs: list[AdminPhase2ResolvedRefPreview] = []

    for ref, source_ids in evidence_ref_sources.items():
        ref_kind = classify_phase2_ref(ref)
        node_type: str | None = None
        resolved = False
        if ref_kind in {Phase2RefKind.ARTIFACT, Phase2RefKind.BRAIN_NODE}:
            try:
                node = store.load_node(ref)
            except KeyError:
                resolved = False
            else:
                resolved = True
                node_type = node.type.value

        resolved_refs.append(
            AdminPhase2ResolvedRefPreview(
                ref=ref,
                ref_kind=ref_kind.value,
                resolved=resolved,
                node_type=node_type,
                source_ids=source_ids,
            )
        )

    return tuple(resolved_refs)


def _artifact_previews_for_preview(
    store: BrainFileStore,
    *,
    artifact_refs: tuple[str, ...],
    evidence_ref_sources: dict[str, tuple[str, ...]],
) -> tuple[AdminPhase2ArtifactPreview, ...]:
    previews: list[AdminPhase2ArtifactPreview] = []

    for artifact_ref in artifact_refs:
        artifact = _load_required(store, artifact_ref, Artifact)
        previews.append(
            AdminPhase2ArtifactPreview(
                id=artifact.id,
                artifact_kind=artifact.artifact_kind.value,
                uri=artifact.uri,
                media_type=artifact.media_type,
                captured_at=artifact.captured_at,
                metadata_keys=tuple(sorted(artifact.metadata)),
                source_ids=evidence_ref_sources.get(artifact.id, ()),
            )
        )

    return tuple(previews)


def _phase1_adapter_evidence_for_preview(
    store: BrainFileStore,
) -> tuple[AdminPhase1AdapterEvidencePreview, ...]:
    artifacts_by_incident: dict[str, list[str]] = {}
    fact_ids_by_incident: dict[str, list[str]] = {}
    measurements_by_incident: dict[str, list[AdminPhase1AdapterMeasurementPreview]] = {}
    fact_links_by_incident: dict[str, dict[str, list[str]]] = {}
    measurement_links_by_incident: dict[
        str,
        dict[str, list[AdminPhase1AdapterMeasurementPreview]],
    ] = {}

    for node in store.list_nodes():
        if isinstance(node, Artifact) and node.id.startswith("artifact.phase1_"):
            incident_id = _phase1_incident_id_for_node(node)
            if incident_id is not None:
                artifacts_by_incident.setdefault(incident_id, []).append(node.id)
            continue

        if isinstance(node, ObservedFact) and node.id.startswith("fact.phase1_"):
            incident_id = _phase1_incident_id_for_node(node)
            if incident_id is not None:
                fact_ids_by_incident.setdefault(incident_id, []).append(node.id)
                for artifact_ref in _phase1_source_artifact_refs(node):
                    fact_links_by_incident.setdefault(incident_id, {}).setdefault(
                        artifact_ref,
                        [],
                    ).append(node.id)
            continue

        if isinstance(node, DerivedMeasurement) and _is_phase1_adapter_measurement(node):
            incident_id = _phase1_incident_id_for_node(node)
            if incident_id is not None:
                measurement_preview = AdminPhase1AdapterMeasurementPreview(
                    id=node.id,
                    metric=node.metric,
                    value=node.value,
                    unit=node.unit,
                    artifact_refs=tuple(node.artifact_refs),
                )
                measurements_by_incident.setdefault(incident_id, []).append(measurement_preview)
                for artifact_ref in _phase1_source_artifact_refs(node):
                    measurement_links_by_incident.setdefault(incident_id, {}).setdefault(
                        artifact_ref,
                        [],
                    ).append(measurement_preview)

    incident_ids = sorted(
        set(artifacts_by_incident) | set(fact_ids_by_incident) | set(measurements_by_incident)
    )
    previews: list[AdminPhase1AdapterEvidencePreview] = []
    for incident_id in incident_ids:
        artifact_refs = tuple(sorted(_dedupe(artifacts_by_incident.get(incident_id, []))))
        fact_ids = tuple(sorted(_dedupe(fact_ids_by_incident.get(incident_id, []))))
        measurements = tuple(
            sorted(
                measurements_by_incident.get(incident_id, []),
                key=lambda measurement: (measurement.metric, measurement.id),
            )
        )
        artifact_source_links = _phase1_artifact_source_links_for_preview(
            artifact_refs=artifact_refs,
            fact_links=fact_links_by_incident.get(incident_id, {}),
            measurement_links=measurement_links_by_incident.get(incident_id, {}),
        )
        source_artifact_ids = tuple(
            link.artifact_ref for link in artifact_source_links if link.evidence_count > 0
        )
        previews.append(
            AdminPhase1AdapterEvidencePreview(
                incident_id=incident_id,
                artifact_refs=artifact_refs,
                source_artifact_ids=source_artifact_ids,
                fact_ids=fact_ids,
                measurement_metrics=measurements,
                artifact_source_links=artifact_source_links,
                artifact_count=len(artifact_refs),
                fact_count=len(fact_ids),
                measurement_count=len(measurements),
            )
        )

    return tuple(previews)


def _phase1_artifact_source_links_for_preview(
    *,
    artifact_refs: tuple[str, ...],
    fact_links: dict[str, list[str]],
    measurement_links: dict[str, list[AdminPhase1AdapterMeasurementPreview]],
) -> tuple[AdminPhase1AdapterArtifactLinkPreview, ...]:
    links: list[AdminPhase1AdapterArtifactLinkPreview] = []
    for artifact_ref in artifact_refs:
        fact_ids = tuple(sorted(_dedupe(fact_links.get(artifact_ref, []))))
        measurements = sorted(
            measurement_links.get(artifact_ref, []),
            key=lambda measurement: (measurement.metric, measurement.id),
        )
        measurement_ids = tuple(_dedupe(measurement.id for measurement in measurements))
        measurement_metrics = tuple(_dedupe(measurement.metric for measurement in measurements))
        links.append(
            AdminPhase1AdapterArtifactLinkPreview(
                artifact_ref=artifact_ref,
                fact_ids=fact_ids,
                measurement_ids=measurement_ids,
                measurement_metrics=measurement_metrics,
                evidence_count=len(fact_ids) + len(measurement_ids),
            )
        )
    return tuple(links)


def _phase1_incident_id_for_node(node: Artifact | ObservedFact | DerivedMeasurement) -> str | None:
    if isinstance(node, Artifact):
        metadata_incident_id = node.metadata.get("incident_id")
        if isinstance(metadata_incident_id, str) and metadata_incident_id:
            return metadata_incident_id
        for artifact_prefix in (
            "artifact.phase1_incident.",
            "artifact.phase1_raw_window.",
            "artifact.phase1_summary.",
            "artifact.phase1_route_evidence.",
            "artifact.phase1_map_evidence.",
        ):
            if node.id.startswith(artifact_prefix):
                return node.id.removeprefix(artifact_prefix)

    for candidate in [getattr(node, "subject", None), *node.artifact_refs]:
        if isinstance(candidate, str) and candidate.startswith("incident."):
            return candidate.removeprefix("incident.")
        if isinstance(candidate, str):
            incident_id = _phase1_incident_id_from_artifact_ref(candidate)
            if incident_id is not None:
                return incident_id

    return None


def _is_phase1_adapter_measurement(node: DerivedMeasurement) -> bool:
    return node.id.startswith("measurement.phase1_") or node.method.startswith("phase1_")


def _phase1_source_artifact_refs(node: ObservedFact | DerivedMeasurement) -> tuple[str, ...]:
    refs = [*node.artifact_refs]
    if isinstance(node, ObservedFact):
        refs.extend(node.evidence)
    if isinstance(node, DerivedMeasurement):
        refs.extend(node.derived_from)
    return tuple(
        ref
        for ref in _dedupe(refs)
        if classify_phase2_ref(ref) == Phase2RefKind.ARTIFACT
    )


def _phase1_incident_id_from_artifact_ref(ref: str) -> str | None:
    for artifact_prefix in (
        "artifact.phase1_incident.",
        "artifact.phase1_raw_window.",
        "artifact.phase1_summary.",
        "artifact.phase1_route_evidence.",
        "artifact.phase1_map_evidence.",
    ):
        if ref.startswith(artifact_prefix):
            return ref.removeprefix(artifact_prefix)
    return None


def _record_ref_source(sources: dict[str, list[str]], ref: str, source_id: str) -> None:
    source_ids = sources.setdefault(ref, [])
    if source_id not in source_ids:
        source_ids.append(source_id)


def _load_required(
    store: BrainFileStore,
    node_id: str,
    expected_type: type[BrainNodeT],
) -> BrainNodeT:
    try:
        node = store.load_node(node_id)
    except KeyError as exc:
        raise MissingBrainReferenceError(f"required Brain ref is missing: {node_id}") from exc

    if not isinstance(node, expected_type):
        raise MissingBrainReferenceError(
            f"required Brain ref {node_id} is {type(node).__name__}, expected {expected_type.__name__}"
        )
    return node


def _is_artifact_ref(store: BrainFileStore, ref: str) -> bool:
    try:
        node = store.load_node(ref)
    except KeyError:
        return False
    return isinstance(node, Artifact)


def _dedupe(refs: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(refs))
