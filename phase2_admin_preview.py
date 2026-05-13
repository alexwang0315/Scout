from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, TypeVar

from case_replay import score_case_replay
from phase2_brain_models import (
    Artifact,
    BrainNode,
    BrainNodeType,
    DecisionOptionSet,
    Mission,
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
