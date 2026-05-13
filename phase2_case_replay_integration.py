from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypeVar

from case_replay import (
    CaseReplay,
    CaseReplayVerdict,
    PostIncidentEvidence,
    ReplayAssessment,
    TimelineCheckpoint,
    score_case_replay,
)
from phase2_brain_models import (
    Artifact,
    BrainNode,
    DecisionOptionSet,
    RemoteStatusArtifact,
    SkillRunRecord,
    TeamSeparationEvent,
)
from phase2_brain_store import BrainFileStore
from phase2_demo_defaults import (
    DEFAULT_OPTION_SET_REF,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_SEPARATION_EVENT_REF,
    DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    DEFAULT_SKILL_RUN_REFS,
)
from phase2_team_replay_store import TeamReplayStoreResult, persist_team_replay_to_brain_store


BrainNodeT = TypeVar("BrainNodeT", bound=BrainNode)


class MissingBrainReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class CaseReplayIntegrationResult:
    persisted: TeamReplayStoreResult
    case: CaseReplay
    verdict: CaseReplayVerdict


def persist_team_replay_and_score_case(
    store: BrainFileStore,
    *,
    fixture_path: Path | str = DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    remote_status_ref: str = DEFAULT_REMOTE_STATUS_REF,
    option_set_ref: str | None = DEFAULT_OPTION_SET_REF,
    separation_event_ref: str | None = DEFAULT_SEPARATION_EVENT_REF,
    skill_run_refs: Iterable[str] = DEFAULT_SKILL_RUN_REFS,
) -> CaseReplayIntegrationResult:
    persisted = persist_team_replay_to_brain_store(store, fixture_path)
    case = build_case_replay_from_brain(
        store,
        remote_status_ref=remote_status_ref,
        option_set_ref=option_set_ref,
        separation_event_ref=separation_event_ref,
        skill_run_refs=skill_run_refs,
    )
    verdict = score_case_replay(case)
    return CaseReplayIntegrationResult(persisted=persisted, case=case, verdict=verdict)


def build_case_replay_from_brain(
    store: BrainFileStore,
    *,
    remote_status_ref: str = DEFAULT_REMOTE_STATUS_REF,
    option_set_ref: str | None = DEFAULT_OPTION_SET_REF,
    separation_event_ref: str | None = DEFAULT_SEPARATION_EVENT_REF,
    skill_run_refs: Iterable[str] = DEFAULT_SKILL_RUN_REFS,
) -> CaseReplay:
    remote_status = _load_required(store, remote_status_ref, RemoteStatusArtifact)
    artifacts = [_load_required(store, ref, Artifact) for ref in remote_status.artifact_refs]
    skill_runs = [
        _load_required(store, skill_run_ref, SkillRunRecord) for skill_run_ref in skill_run_refs
    ]

    if option_set_ref is None and separation_event_ref is None:
        return _build_nominal_case(remote_status, artifacts, skill_runs)

    if option_set_ref is None or separation_event_ref is None:
        raise MissingBrainReferenceError(
            "case replay requires option and separation refs together, or neither for nominal replay"
        )

    option_set = _load_required(store, option_set_ref, DecisionOptionSet)
    separation_event = _load_required(store, separation_event_ref, TeamSeparationEvent)
    if len(skill_runs) < 2:
        raise MissingBrainReferenceError("case replay requires remote-status and option skill run refs")

    _require_ref(option_set.input_refs, remote_status.id, owner=option_set.id)
    _require_ref(option_set.input_refs, separation_event.id, owner=option_set.id)
    _require_ref(separation_event.evidence_refs, remote_status.id, owner=separation_event.id)
    for skill_run in skill_runs:
        _require_skill_run_link(skill_run, remote_status, option_set, separation_event)

    artifact_refs = [artifact.id for artifact in artifacts]
    skill_run_ids = [skill_run.id for skill_run in skill_runs]

    return CaseReplay(
        case_id="case.phase2.ridge_loop_brain_persisted_replay",
        title="Persisted Brain replay for ridge loop possible separation",
        incident_type="possible team separation",
        location="North ridge loop near Misty saddle",
        route_context="Same-day loop with delayed checkpoint arrival and stale member status.",
        incident_at=separation_event.detected_at,
        timeline=[
            TimelineCheckpoint(
                label="T-120",
                minutes_to_incident=-120,
                safety_level="L0",
                summary="Brain replay begins from persisted route and team context before the saddle delay.",
                artifact_refs=artifact_refs,
            ),
            TimelineCheckpoint(
                label="T-60",
                minutes_to_incident=-60,
                safety_level="L1",
                summary=(
                    "Persisted remote status shows delayed progress and stale member freshness."
                ),
                evidence_refs=[remote_status.id, skill_run_ids[0]],
                artifact_refs=artifact_refs,
                remote_status_ref=remote_status.id,
            ),
            TimelineCheckpoint(
                label="T-30",
                minutes_to_incident=-30,
                safety_level="L2",
                summary=(
                    "Persisted separation event and degraded decision option run create "
                    "an auditable decision window."
                ),
                evidence_refs=[separation_event.id, skill_run_ids[1]],
                artifact_refs=artifact_refs,
                remote_status_ref=remote_status.id,
                option_set_ref=option_set.id,
            ),
            TimelineCheckpoint(
                label="T-0",
                minutes_to_incident=0,
                safety_level="L2",
                summary=(
                    "Replay ends with bounded decision options and skill audit refs, "
                    "without claiming an assured field outcome."
                ),
                evidence_refs=[option_set.id, *skill_run_ids],
                artifact_refs=artifact_refs,
                remote_status_ref=remote_status.id,
                option_set_ref=option_set.id,
            ),
        ],
        post_incident_evidence=[
            PostIncidentEvidence(
                id="post.ridge_loop.persisted_brain_refs",
                captured_after_minutes=180,
                evidence_type="incident_package",
                summary="After-action package is reconstructed from persisted Brain node references.",
                artifact_refs=artifact_refs,
            )
        ],
        baseline_summary=(
            "Without persisted Brain refs, the case replay would rely on fixture text rather "
            "than auditable remote status, separation, option, skill run, and artifact nodes."
        ),
        replay_summary=(
            "Persisted Brain refs show earlier awareness and a reversible hold/regroup "
            "decision window under degraded L2 handling."
        ),
        known_outcome_summary=(
            "The synthetic team replay demonstrates evidence and decision timing only; "
            "it does not assert an assured field result."
        ),
        assessment=ReplayAssessment(
            evidence_improved=True,
            earlier_awareness_minutes=60,
            decision_window_minutes=30,
            likely_outcome_improvement=False,
            guaranteed_outcome=False,
            rationale=(
                "Persisted Brain references support an earlier awareness signal and a "
                "bounded decision window, but do not prove an assured field outcome."
            ),
        ),
    )


def _build_nominal_case(
    remote_status: RemoteStatusArtifact,
    artifacts: list[Artifact],
    skill_runs: list[SkillRunRecord],
) -> CaseReplay:
    if not skill_runs:
        raise MissingBrainReferenceError("nominal case replay requires at least one skill run ref")
    for skill_run in skill_runs:
        _require_remote_status_skill_run_link(skill_run, remote_status)

    artifact_refs = [artifact.id for artifact in artifacts]
    skill_run_ids = [skill_run.id for skill_run in skill_runs]
    latest_checkpoint = remote_status.latest_checkpoint or "latest checkpoint"
    member_total = remote_status.team_summary.get("members_total", "team")
    member_fresh = remote_status.team_summary.get("members_fresh", "fresh")

    return CaseReplay(
        case_id=f"case.phase2.{_case_slug(remote_status.id)}.nominal_remote_status_replay",
        title="Persisted Brain replay for nominal remote status check-in",
        incident_type="nominal team status",
        location=latest_checkpoint,
        route_context=(
            f"Two-person team replay with {member_fresh}/{member_total} fresh members "
            "and no persisted separation event."
        ),
        incident_at=remote_status.generated_at,
        timeline=[
            TimelineCheckpoint(
                label="T-60",
                minutes_to_incident=-60,
                safety_level="L0",
                summary="Brain replay begins from persisted team route context before the remote check-in.",
                artifact_refs=artifact_refs,
            ),
            TimelineCheckpoint(
                label="T-0",
                minutes_to_incident=0,
                safety_level=remote_status.safety_level,
                summary=(
                    "Persisted remote status and skill run refs show a bounded nominal "
                    "check-in without creating separation or decision-option evidence."
                ),
                evidence_refs=[remote_status.id, *skill_run_ids],
                artifact_refs=artifact_refs,
                remote_status_ref=remote_status.id,
            ),
        ],
        baseline_summary=(
            "Without persisted Brain refs, the nominal check-in would only be fixture text "
            "rather than auditable remote status, skill run, and artifact nodes."
        ),
        replay_summary=(
            "Persisted Brain refs preserve the nominal remote status path without inventing "
            "a separation event, safety incident, or option set."
        ),
        known_outcome_summary=(
            "The synthetic team replay demonstrates provenance for a non-anomalous check-in only."
        ),
        assessment=ReplayAssessment(
            evidence_improved=True,
            earlier_awareness_minutes=0,
            decision_window_minutes=0,
            likely_outcome_improvement=False,
            guaranteed_outcome=False,
            rationale=(
                "Persisted remote status, skill run, and artifact refs improve auditability "
                "for a nominal team replay without claiming anomaly handling or outcome change."
            ),
        ),
    )


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


def _require_ref(refs: list[str], required_ref: str, *, owner: str) -> None:
    if required_ref not in refs:
        raise MissingBrainReferenceError(f"{owner} does not reference required Brain ref {required_ref}")


def _require_skill_run_link(
    skill_run: SkillRunRecord,
    remote_status: RemoteStatusArtifact,
    option_set: DecisionOptionSet,
    separation_event: TeamSeparationEvent,
) -> None:
    linked_refs = set(skill_run.input_refs) | set(skill_run.output_refs)
    expected_refs = {remote_status.id, option_set.id, separation_event.id}
    if linked_refs.isdisjoint(expected_refs):
        raise MissingBrainReferenceError(
            f"{skill_run.id} is not linked to required case replay Brain refs"
        )


def _require_remote_status_skill_run_link(
    skill_run: SkillRunRecord,
    remote_status: RemoteStatusArtifact,
) -> None:
    linked_refs = set(skill_run.input_refs) | set(skill_run.output_refs)
    if remote_status.id not in linked_refs:
        raise MissingBrainReferenceError(
            f"{skill_run.id} is not linked to required nominal remote status Brain ref"
        )


def _case_slug(node_id: str) -> str:
    return node_id.removeprefix("remote_status.").replace(".", "_")
