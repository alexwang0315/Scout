from __future__ import annotations

import fnmatch
import hashlib
import json
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Sequence


Actor = Literal[
    "system",
    "human_decision",
    "test_fixture_input",
    "observation",
    "idempotent_retry",
    "repair_action",
]


@dataclass(frozen=True)
class PermissionQualificationState:
    state_id: str
    baseline_capability: str
    baseline_lifecycle: str
    required_inputs: str
    baseline_review_binding: str
    migration: str
    projection: str
    policy_review: str
    rebuild_admission: str
    outcome: str
    root_blocker_ids: tuple[str, ...] = ()
    artifact_identity: str | None = None
    parent_identities: tuple[str, ...] = ()
    command_snapshot_sha256: str | None = None
    evaluator_version: str | None = None
    forbidden_effects: tuple[str, ...] = ()

    def with_changes(self, **changes: object) -> "PermissionQualificationState":
        return replace(self, **changes)

    def progress_signature(self) -> tuple[object, ...]:
        """Return semantic obligations, excluding volatile artifact identities."""

        return (
            self.baseline_capability,
            self.baseline_lifecycle,
            self.required_inputs,
            self.baseline_review_binding,
            self.migration,
            self.projection,
            self.policy_review,
            self.rebuild_admission,
            self.outcome,
            tuple(sorted(self.root_blocker_ids)),
            tuple(sorted(self.parent_identities)),
            self.command_snapshot_sha256,
            self.evaluator_version,
            tuple(sorted(self.forbidden_effects)),
        )


@dataclass(frozen=True)
class PermissionTransition:
    transition_id: str
    source_state_id: str
    target_state_id: str
    actor: Actor
    intent: Actor
    advertised_as_recovery: bool = False
    typed_no_progress: bool = False
    http_status: int | None = None
    recovery_rank_before: int | None = None
    recovery_rank_after: int | None = None
    effects: tuple[str, ...] = ()
    forbidden_effects: tuple[str, ...] = ()
    command_id: str | None = None
    snapshot_sha256: str | None = None
    evaluator_version: str | None = None
    read_side_eligible: bool | None = None
    command_admitted: bool | None = None


@dataclass(frozen=True)
class PermissionTrace:
    fixture_id: str
    schema_version: str
    supported_historical_start: bool
    source_evidence: tuple[str, ...]
    start_state_id: str
    supported_start_state_ids: tuple[str, ...]
    states: tuple[PermissionQualificationState, ...]
    transitions: tuple[PermissionTransition, ...]


@dataclass(frozen=True)
class QualificationFinding:
    code: str
    summary: str
    transition_ids: tuple[str, ...]
    state_ids: tuple[str, ...]
    blocker_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    effect_identities: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionQualificationReport:
    ready_reachable: bool
    accepted_terminal_reachable: bool
    findings: tuple[QualificationFinding, ...]
    shortest_counterexample: tuple[str, ...]
    closed_nonterminal_components: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ProjectTreeSnapshot:
    files: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class QualificationEffectTrace:
    transition_id: str
    created_refs: tuple[str, ...]
    modified_refs: tuple[str, ...]
    deleted_refs: tuple[str, ...]
    forbidden_refs: tuple[str, ...]
    forbidden_effect_flags: tuple[str, ...]


_FORBIDDEN_EFFECT_FLAGS = (
    "runtime_safety_truth",
    "departure_approval_granted",
    "active_runtime_session_updated",
    "safety_api_called",
    "outbound_action_performed",
    "outbound_transport_invoked",
    "external_send_performed",
    "hardware_control_performed",
)


def capture_project_tree(project_root: Path) -> ProjectTreeSnapshot:
    root = Path(project_root).resolve()
    files = tuple(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
    )
    return ProjectTreeSnapshot(files=files)


def trace_project_effects(
    transition_id: str,
    before: ProjectTreeSnapshot,
    after: ProjectTreeSnapshot,
    *,
    allowed_ref_patterns: Sequence[str],
    response_payloads: Sequence[object] = (),
) -> QualificationEffectTrace:
    before_files = dict(before.files)
    after_files = dict(after.files)
    created = tuple(sorted(set(after_files) - set(before_files)))
    deleted = tuple(sorted(set(before_files) - set(after_files)))
    modified = tuple(
        sorted(
            ref
            for ref in set(before_files) & set(after_files)
            if before_files[ref] != after_files[ref]
        )
    )
    changed = (*created, *modified, *deleted)
    forbidden_refs = tuple(
        sorted(
            ref
            for ref in changed
            if not any(
                fnmatch.fnmatchcase(ref, pattern)
                for pattern in allowed_ref_patterns
            )
        )
    )
    forbidden_effect_flags = tuple(
        sorted(
            {
                flag
                for payload in response_payloads
                for flag in _FORBIDDEN_EFFECT_FLAGS
                if isinstance(payload, dict) and payload.get(flag) is True
            }
        )
    )
    return QualificationEffectTrace(
        transition_id=transition_id,
        created_refs=created,
        modified_refs=modified,
        deleted_refs=deleted,
        forbidden_refs=forbidden_refs,
        forbidden_effect_flags=forbidden_effect_flags,
    )


def extract_permission_state(
    project_root: Path,
    *,
    state_id: str,
) -> PermissionQualificationState:
    """Extract qualification truth without calling production admission code."""

    root = Path(project_root).resolve()
    project = _read_json_object(root / "project.json")
    reviewed_ref = str(project.get("reviewed_mission_baseline_ref") or "")
    reviewed_sha256 = str(project.get("reviewed_mission_baseline_sha256") or "")
    reviewed = _read_json_object(root / reviewed_ref) if reviewed_ref else {}
    profile = reviewed.get("proposal_profile")
    explicit_capability = reviewed.get("capability_version")
    if explicit_capability in {"legacy_sparse.v1", "ref_gpx_proposal.v1"}:
        baseline_capability = str(explicit_capability)
    elif profile in {None, "legacy_sparse"} and reviewed_ref:
        baseline_capability = "legacy_sparse.v1"
    elif profile == "ref_gpx_proposal_v1":
        baseline_capability = "ref_gpx_proposal.v1"
    elif reviewed_ref:
        baseline_capability = "unknown_or_unsupported"
    else:
        baseline_capability = "absent"

    baseline_lifecycle = "current" if reviewed_ref else "absent"
    review_binding = _independent_review_binding(
        root=root,
        reviewed_ref=reviewed_ref,
        reviewed_sha256=reviewed_sha256,
        reviewed=reviewed,
    )
    required_inputs = _independent_required_inputs(
        root=root,
        project=project,
        reviewed=reviewed,
        capability=baseline_capability,
    )
    pending_rebuild_transactions = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in (
                root / "reviews/contextual_permission_rebuild_transactions"
            ).glob("*.json")
            if path.is_file()
        )
    )
    pending_activation_transactions = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in (
                root / "reviews/mission_baseline_accept_transactions"
            ).glob("*.json")
            if path.is_file()
        )
    )
    seed = _read_json_object(
        root / "outputs/contextual_permission/workbench_seed.json"
    )
    seed_baseline = seed.get("baseline") if isinstance(seed.get("baseline"), dict) else {}
    rules_ref = str(
        project.get("contextual_permission_rules_ref")
        or "candidates/contextual_permission_rules.json"
    )
    rules = _read_json_object(root / rules_ref)
    rules_baseline_sha256 = str(rules.get("reviewed_baseline_sha256") or "")
    seed_baseline_sha256 = str(seed_baseline.get("baseline_sha256") or "")
    if pending_rebuild_transactions or pending_activation_transactions:
        projection = "orphaned_or_write_in_doubt"
    elif not seed:
        projection = "absent"
    elif (
        review_binding == "current"
        and required_inputs == "complete"
        and reviewed_sha256
        and seed_baseline_sha256 == reviewed_sha256
        and rules_baseline_sha256 == reviewed_sha256
    ):
        projection = "fresh"
    else:
        projection = "stale"

    if not rules:
        policy_review = "not_required" if projection == "absent" else "stale"
    elif (
        projection != "fresh"
        or review_binding != "current"
        or required_inputs != "complete"
        or rules_baseline_sha256 != reviewed_sha256
    ):
        policy_review = "stale"
    elif rules.get("reviewed_by_human") is True:
        policy_review = (
            "current"
            if _independent_policy_review_binding(
                root=root,
                rules_ref=rules_ref,
                rules=rules,
            )
            else "stale"
        )
    else:
        policy_review = "pending"

    trail_days = [
        day
        for day in reviewed.get("days") or []
        if isinstance(day, dict) and day.get("day_kind") == "on_trail"
    ]
    complete_day_ends = bool(trail_days) and all(
        isinstance(day.get("primary_day_end_proposal"), dict)
        for day in trail_days
    )
    independently_eligible = (
        baseline_capability == "ref_gpx_proposal.v1"
        and review_binding == "current"
        and required_inputs == "complete"
        and complete_day_ends
        and not pending_rebuild_transactions
        and not pending_activation_transactions
    )
    rebuild_admission = "eligible" if independently_eligible else "blocked"
    migration = (
        "required"
        if baseline_capability == "legacy_sparse.v1"
        else "accepted"
        if baseline_capability == "ref_gpx_proposal.v1" and review_binding == "current"
        else "blocked"
        if reviewed_ref
        else "none"
    )

    root_blockers: list[str] = []
    if pending_activation_transactions:
        root_blockers.append("baseline_activation_write_in_doubt")
    if pending_rebuild_transactions:
        root_blockers.append("contextual_permission_projection_write_in_doubt")
    if reviewed_ref and review_binding != "current":
        root_blockers.append("baseline_review_binding_stale")
    if baseline_capability == "legacy_sparse.v1":
        root_blockers.append("baseline_migration_required")
    elif required_inputs != "complete" and reviewed_ref:
        root_blockers.append(f"required_inputs_{required_inputs}")
    elif baseline_capability == "ref_gpx_proposal.v1" and not complete_day_ends:
        root_blockers.append("reviewed_baseline_missing_day_end_bindings")
    if projection == "stale" and not root_blockers:
        root_blockers.append("projection_dependency_stale")
    if policy_review == "pending":
        root_blockers.append("contextual_permission_rules_review_pending")

    if (
        projection == "fresh"
        and policy_review == "current"
        and independently_eligible
        and not root_blockers
    ):
        outcome = "ready"
    elif (
        baseline_capability == "legacy_sparse.v1"
        and review_binding == "current"
    ):
        outcome = "safely_blocked_for_migration"
    else:
        outcome = "invalid"

    review_id = str(reviewed.get("review_id") or "")
    candidate_ref = str(reviewed.get("candidate_ref") or "")
    timing_ref = str(project.get("reference_segment_timing_ref") or "")
    graph_ref = str(project.get("compiled_mission_graph_reviewed_ref") or "")
    review_receipt_ref = (
        f"reviews/mission_baseline_accept_receipts/{review_id}.json"
        if review_id
        else ""
    )
    rules_review_receipt_ref = str(rules.get("review_receipt_ref") or "")
    parent_identities = tuple(
        sorted(
            identity
            for identity in (
                str(reviewed.get("candidate_sha256") or ""),
                _file_digest(root / candidate_ref) if candidate_ref else "",
                _file_digest(root / review_receipt_ref)
                if review_receipt_ref
                else "",
                _file_digest(root / timing_ref) if timing_ref else "",
                _file_digest(root / graph_ref) if graph_ref else "",
                _file_digest(root / rules_ref),
                _file_digest(root / rules_review_receipt_ref)
                if rules_review_receipt_ref.startswith("reviews/")
                else "",
                _file_digest(
                    root / "outputs/contextual_permission/workbench_seed.json"
                ),
                *(
                    _file_digest(root / ref)
                    for ref in pending_activation_transactions
                ),
                *(
                    _file_digest(root / ref)
                    for ref in pending_rebuild_transactions
                ),
            )
            if identity
        )
    )
    evaluator_version = "contextual-permission.projection-rebuild-admission.v1"
    command_snapshot_sha256 = _canonical_digest(
        {
            "reviewed_baseline_ref": reviewed_ref or None,
            "reviewed_baseline_sha256": reviewed_sha256 or None,
            "reviewed_file_sha256": (
                _file_digest(root / reviewed_ref) if reviewed_ref else None
            ),
            "candidate_ref": candidate_ref or None,
            "candidate_sha256": reviewed.get("candidate_sha256"),
            "candidate_file_sha256": (
                _file_digest(root / candidate_ref) if candidate_ref else None
            ),
            "review_receipt_ref": review_receipt_ref or None,
            "review_receipt_file_sha256": (
                _file_digest(root / review_receipt_ref)
                if review_receipt_ref
                else None
            ),
            "graph_ref": graph_ref or None,
            "graph_file_sha256": (
                _file_digest(root / graph_ref) if graph_ref else None
            ),
            "timing_ref": timing_ref or None,
            "timing_file_sha256": (
                _file_digest(root / timing_ref) if timing_ref else None
            ),
            "admission_version": evaluator_version,
        }
    )
    return PermissionQualificationState(
        state_id=state_id,
        baseline_capability=baseline_capability,
        baseline_lifecycle=baseline_lifecycle,
        required_inputs=required_inputs,
        baseline_review_binding=review_binding,
        migration=migration,
        projection=projection,
        policy_review=policy_review,
        rebuild_admission=rebuild_admission,
        outcome=outcome,
        root_blocker_ids=tuple(sorted(set(root_blockers))),
        artifact_identity=reviewed_sha256 or None,
        parent_identities=parent_identities,
        command_snapshot_sha256=command_snapshot_sha256,
        evaluator_version=evaluator_version,
        forbidden_effects=(),
    )


def load_permission_trace(path: Path) -> PermissionTrace:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    states = tuple(
        PermissionQualificationState(
            state_id=str(item["state_id"]),
            baseline_capability=str(item["baseline_capability"]),
            baseline_lifecycle=str(item["baseline_lifecycle"]),
            required_inputs=str(item["required_inputs"]),
            baseline_review_binding=str(item["baseline_review_binding"]),
            migration=str(item["migration"]),
            projection=str(item["projection"]),
            policy_review=str(item["policy_review"]),
            rebuild_admission=str(item["rebuild_admission"]),
            outcome=str(item["outcome"]),
            root_blocker_ids=tuple(item.get("root_blocker_ids") or ()),
            artifact_identity=item.get("artifact_identity"),
            parent_identities=tuple(item.get("parent_identities") or ()),
            command_snapshot_sha256=item.get("command_snapshot_sha256"),
            evaluator_version=item.get("evaluator_version"),
            forbidden_effects=tuple(item.get("forbidden_effects") or ()),
        )
        for item in payload["states"]
    )
    transitions = tuple(
        PermissionTransition(
            transition_id=str(item["transition_id"]),
            source_state_id=str(item["source_state_id"]),
            target_state_id=str(item["target_state_id"]),
            actor=str(item["actor"]),  # type: ignore[arg-type]
            intent=str(item["intent"]),  # type: ignore[arg-type]
            advertised_as_recovery=bool(item.get("advertised_as_recovery")),
            typed_no_progress=bool(item.get("typed_no_progress")),
            http_status=item.get("http_status"),
            recovery_rank_before=item.get("recovery_rank_before"),
            recovery_rank_after=item.get("recovery_rank_after"),
            effects=tuple(item.get("effects") or ()),
            forbidden_effects=tuple(item.get("forbidden_effects") or ()),
            command_id=item.get("command_id"),
            snapshot_sha256=item.get("snapshot_sha256"),
            evaluator_version=item.get("evaluator_version"),
            read_side_eligible=item.get("read_side_eligible"),
            command_admitted=item.get("command_admitted"),
        )
        for item in payload["transitions"]
    )
    return PermissionTrace(
        fixture_id=str(payload["fixture_id"]),
        schema_version=str(payload["schema_version"]),
        supported_historical_start=bool(payload["supported_historical_start"]),
        source_evidence=tuple(payload.get("source_evidence") or ()),
        start_state_id=str(payload["start_state_id"]),
        supported_start_state_ids=tuple(
            payload.get("supported_start_state_ids") or (payload["start_state_id"],)
        ),
        states=states,
        transitions=transitions,
    )


def analyze_permission_graph(
    states_or_trace: PermissionTrace | Sequence[PermissionQualificationState],
    transitions: Sequence[PermissionTransition] | None = None,
    *,
    start_state_id: str | None = None,
) -> PermissionQualificationReport:
    if isinstance(states_or_trace, PermissionTrace):
        states = states_or_trace.states
        resolved_transitions = states_or_trace.transitions
        resolved_start = states_or_trace.start_state_id
    else:
        states = tuple(states_or_trace)
        resolved_transitions = tuple(transitions or ())
        resolved_start = start_state_id or (states[0].state_id if states else "")
    by_id = {state.state_id: state for state in states}
    if len(by_id) != len(states):
        raise ValueError("qualification state IDs must be unique")
    if resolved_start not in by_id:
        raise ValueError("qualification start state is missing")
    for transition in resolved_transitions:
        if (
            transition.source_state_id not in by_id
            or transition.target_state_id not in by_id
        ):
            raise ValueError("qualification transition references an unknown state")

    outgoing: dict[str, list[PermissionTransition]] = {
        state_id: [] for state_id in by_id
    }
    for transition in resolved_transitions:
        outgoing[transition.source_state_id].append(transition)
    for values in outgoing.values():
        values.sort(key=lambda item: item.transition_id)

    reachable = _reachable_state_ids(resolved_start, outgoing)
    ready_reachable = any(by_id[state_id].outcome == "ready" for state_id in reachable)
    accepted_terminal_reachable = any(
        by_id[state_id].outcome in {"ready", "safely_blocked_for_migration"}
        for state_id in reachable
    )
    components = _strongly_connected_components(reachable, outgoing)
    closed_nonterminal = tuple(
        tuple(sorted(component))
        for component in components
        if _is_closed_nonterminal_component(component, by_id, outgoing)
    )
    closed_nonterminal = tuple(sorted(closed_nonterminal))

    recovery_violations = tuple(
        transition
        for transition in resolved_transitions
        if transition.source_state_id in reachable
        and transition.advertised_as_recovery
        and not transition.typed_no_progress
        and (
            by_id[transition.source_state_id].progress_signature()
            == by_id[transition.target_state_id].progress_signature()
            or (
                transition.recovery_rank_before is not None
                and transition.recovery_rank_after is not None
                and transition.recovery_rank_after
                >= transition.recovery_rank_before
            )
        )
    )

    counterexample: tuple[str, ...] = ()
    state_evidence: tuple[str, ...] = ()
    if closed_nonterminal:
        component = set(closed_nonterminal[0])
        path = _shortest_path_to_component(resolved_start, component, outgoing)
        entry_state = _path_target(resolved_start, path, resolved_transitions)
        cycle = _shortest_cycle(entry_state, component, outgoing)
        counterexample = (*path, *cycle)
        state_evidence = closed_nonterminal[0]
    elif recovery_violations:
        violation = recovery_violations[0]
        path = _shortest_path_to_component(
            resolved_start, {violation.source_state_id}, outgoing
        )
        counterexample = (*path, violation.transition_id)
        state_evidence = (
            violation.source_state_id,
            violation.target_state_id,
        )

    finding_items: list[QualificationFinding] = []
    if counterexample:
        counterexample_transitions = [
            transition
            for transition in resolved_transitions
            if transition.transition_id in counterexample
        ]
        finding_items.append(
            QualificationFinding(
                code="FLOW-LIVELOCK",
                summary=(
                    "An advertised recovery remains in a closed non-terminal "
                    "component or fails to reduce its recovery rank."
                ),
                transition_ids=counterexample,
                state_ids=state_evidence,
                blocker_ids=tuple(
                    sorted(
                        {
                            blocker
                            for state_id in state_evidence
                            for blocker in by_id[state_id].root_blocker_ids
                        }
                    )
                ),
                capability_ids=tuple(
                    sorted(
                        {by_id[state_id].baseline_capability for state_id in state_evidence}
                    )
                ),
                effect_identities=tuple(
                    sorted(
                        {
                            effect
                            for transition in counterexample_transitions
                            for effect in transition.effects
                        }
                    )
                ),
            )
        )
    predicate_violations = [
        transition
        for transition in resolved_transitions
        if transition.source_state_id in reachable
        and transition.command_id
        and transition.snapshot_sha256
        and transition.evaluator_version
        and transition.read_side_eligible is not None
        and transition.command_admitted is not None
        and transition.read_side_eligible != transition.command_admitted
    ]
    if predicate_violations:
        transition = predicate_violations[0]
        finding_items.append(
            QualificationFinding(
                code="PREDICATE-DIVERGENCE",
                summary=(
                    "Read-side eligibility and command admission disagree for "
                    "the same command, snapshot, and evaluator identity."
                ),
                transition_ids=(transition.transition_id,),
                state_ids=(transition.source_state_id,),
            )
        )
    invalid_ready_states = [
        by_id[state_id]
        for state_id in sorted(reachable)
        if by_id[state_id].outcome == "ready"
        and (
            by_id[state_id].baseline_review_binding != "current"
            or by_id[state_id].projection != "fresh"
            or by_id[state_id].policy_review not in {"current", "not_required"}
            or by_id[state_id].rebuild_admission != "eligible"
        )
    ]
    if invalid_ready_states:
        state = invalid_ready_states[0]
        finding_items.append(
            QualificationFinding(
                code="DEPENDENCY-SPLIT-BRAIN",
                summary=(
                    "A state is marked ready without current review, projection, "
                    "policy, and command-admission bindings."
                ),
                transition_ids=(),
                state_ids=(state.state_id,),
            )
        )
    forbidden_transitions = [
        transition
        for transition in resolved_transitions
        if transition.source_state_id in reachable and transition.forbidden_effects
    ]
    forbidden_states = [
        by_id[state_id]
        for state_id in sorted(reachable)
        if by_id[state_id].forbidden_effects
    ]
    if forbidden_transitions or forbidden_states:
        finding_items.append(
            QualificationFinding(
                code="FORBIDDEN-EFFECT",
                summary="Qualification observed an effect outside its candidate-only allowlist.",
                transition_ids=tuple(
                    transition.transition_id for transition in forbidden_transitions
                ),
                state_ids=tuple(state.state_id for state in forbidden_states),
                effect_identities=tuple(
                    sorted(
                        {
                            effect
                            for transition in forbidden_transitions
                            for effect in transition.forbidden_effects
                        }
                        | {
                            effect
                            for state in forbidden_states
                            for effect in state.forbidden_effects
                        }
                    )
                ),
            )
        )
    findings = tuple(finding_items)
    return PermissionQualificationReport(
        ready_reachable=ready_reachable,
        accepted_terminal_reachable=accepted_terminal_reachable,
        findings=findings,
        shortest_counterexample=counterexample,
        closed_nonterminal_components=closed_nonterminal,
    )


def _reachable_state_ids(
    start_state_id: str,
    outgoing: dict[str, list[PermissionTransition]],
) -> set[str]:
    seen = {start_state_id}
    queue = deque([start_state_id])
    while queue:
        state_id = queue.popleft()
        for transition in outgoing[state_id]:
            if transition.target_state_id not in seen:
                seen.add(transition.target_state_id)
                queue.append(transition.target_state_id)
    return seen


def _strongly_connected_components(
    reachable: set[str],
    outgoing: dict[str, list[PermissionTransition]],
) -> tuple[set[str], ...]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[set[str]] = []

    def visit(state_id: str) -> None:
        nonlocal index
        indexes[state_id] = index
        lowlinks[state_id] = index
        index += 1
        stack.append(state_id)
        on_stack.add(state_id)
        for transition in outgoing[state_id]:
            target = transition.target_state_id
            if target not in reachable:
                continue
            if target not in indexes:
                visit(target)
                lowlinks[state_id] = min(lowlinks[state_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[state_id] = min(lowlinks[state_id], indexes[target])
        if lowlinks[state_id] != indexes[state_id]:
            return
        component: set[str] = set()
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.add(member)
            if member == state_id:
                break
        components.append(component)

    for state_id in sorted(reachable):
        if state_id not in indexes:
            visit(state_id)
    return tuple(components)


def _is_closed_nonterminal_component(
    component: set[str],
    states: dict[str, PermissionQualificationState],
    outgoing: dict[str, list[PermissionTransition]],
) -> bool:
    if any(
        states[state_id].outcome in {"ready", "safely_blocked_for_migration"}
        for state_id in component
    ):
        return False
    cyclic = len(component) > 1 or any(
        transition.target_state_id == state_id
        for state_id in component
        for transition in outgoing[state_id]
    )
    if not cyclic:
        return False
    return not any(
        transition.target_state_id not in component
        for state_id in component
        for transition in outgoing[state_id]
    )


def _shortest_path_to_component(
    start_state_id: str,
    targets: set[str],
    outgoing: dict[str, list[PermissionTransition]],
) -> tuple[str, ...]:
    queue = deque([(start_state_id, ())])
    seen = {start_state_id}
    while queue:
        state_id, path = queue.popleft()
        if state_id in targets:
            return path
        for transition in outgoing[state_id]:
            if transition.target_state_id in seen:
                continue
            seen.add(transition.target_state_id)
            queue.append(
                (transition.target_state_id, (*path, transition.transition_id))
            )
    return ()


def _path_target(
    start_state_id: str,
    path: tuple[str, ...],
    transitions: Sequence[PermissionTransition],
) -> str:
    by_id = {transition.transition_id: transition for transition in transitions}
    current = start_state_id
    for transition_id in path:
        transition = by_id[transition_id]
        if transition.source_state_id != current:
            raise ValueError("counterexample path is discontinuous")
        current = transition.target_state_id
    return current


def _shortest_cycle(
    start_state_id: str,
    component: set[str],
    outgoing: dict[str, list[PermissionTransition]],
) -> tuple[str, ...]:
    queue = deque([(start_state_id, ())])
    visited_depth = {start_state_id: 0}
    while queue:
        state_id, path = queue.popleft()
        for transition in outgoing[state_id]:
            if transition.target_state_id not in component:
                continue
            candidate = (*path, transition.transition_id)
            if transition.target_state_id == start_state_id:
                return candidate
            depth = len(candidate)
            prior_depth = visited_depth.get(transition.target_state_id)
            if prior_depth is not None and prior_depth <= depth:
                continue
            visited_depth[transition.target_state_id] = depth
            queue.append((transition.target_state_id, candidate))
    return ()


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _independent_review_binding(
    *,
    root: Path,
    reviewed_ref: str,
    reviewed_sha256: str,
    reviewed: dict[str, object],
) -> str:
    if not reviewed_ref:
        return "none"
    if (
        not reviewed_sha256
        or reviewed.get("reviewed_baseline_sha256") != reviewed_sha256
        or _canonical_digest(
            {
                key: value
                for key, value in reviewed.items()
                if key != "reviewed_baseline_sha256"
            }
        )
        != reviewed_sha256
    ):
        return "stale"
    candidate_ref = str(reviewed.get("candidate_ref") or "")
    candidate_sha256 = str(reviewed.get("candidate_sha256") or "")
    candidate = _read_json_object(root / candidate_ref)
    if (
        not candidate
        or candidate.get("version_sha256") != candidate_sha256
        or _canonical_digest(
            {
                key: value
                for key, value in candidate.items()
                if key != "version_sha256"
            }
        )
        != candidate_sha256
    ):
        return "stale"
    immutable_projection_fields = (
        (
            "source_mode",
            "source_sha256",
            "days",
            "proposal_profile",
            "capability_version",
            "migration_contract_version",
            "day_end_input_contract_sha256",
            "day_end_inputs",
            "proposal_strategy_id",
            "proposal_strategy_version",
            "timing_evidence",
            "proposal_summary",
            "uncertainties",
        )
        if candidate.get("proposal_profile") == "ref_gpx_proposal_v1"
        else ("source_mode", "source_sha256", "days", "proposal_profile")
    )
    if any(
        reviewed.get(field) != candidate.get(field)
        for field in immutable_projection_fields
    ):
        return "stale"
    if (
        candidate.get("proposal_profile") == "legacy_sparse"
        and reviewed.get("capability_version") not in {None, "legacy_sparse.v1"}
    ):
        return "stale"
    review_id = str(reviewed.get("review_id") or "")
    receipt = _read_json_object(
        root / f"reviews/mission_baseline_accept_receipts/{review_id}.json"
    )
    if (
        not receipt
        or receipt.get("reviewed_baseline_ref") != reviewed_ref
        or receipt.get("reviewed_baseline_sha256") != reviewed_sha256
        or receipt.get("review_sha256")
        != _canonical_digest(
            {
                key: value
                for key, value in receipt.items()
                if key != "review_sha256"
            }
        )
    ):
        return "stale"
    return "current"


def _independent_required_inputs(
    *,
    root: Path,
    project: dict[str, object],
    reviewed: dict[str, object],
    capability: str,
) -> str:
    if capability == "ref_gpx_proposal.v1":
        timing = reviewed.get("timing_evidence")
        if not isinstance(timing, dict):
            return "missing"
        timing_ref = str(timing.get("ref") or "")
        expected_sha256 = str(timing.get("sha256") or "")
        if not timing_ref or not (root / timing_ref).is_file():
            return "missing"
        return (
            "complete"
            if _file_digest(root / timing_ref) == expected_sha256
            else "conflicting"
        )
    timing_ref = str(project.get("reference_segment_timing_ref") or "")
    timing_path = root / timing_ref
    if not timing_ref or not timing_path.is_file():
        return "missing"
    timing_payload = _read_json_object(timing_path)
    segments = timing_payload.get("segments")
    checkpoints = timing_payload.get("checkpoint_match_quality")
    if (
        not isinstance(segments, list)
        or not segments
        or not all(
            isinstance(segment, dict) and segment.get("segment_id")
            for segment in segments
        )
        or not isinstance(checkpoints, dict)
        or len(checkpoints) < 2
    ):
        return "conflicting"
    return "complete"


def _independent_policy_review_binding(
    *,
    root: Path,
    rules_ref: str,
    rules: dict[str, object],
) -> bool:
    receipt_ref = str(rules.get("review_receipt_ref") or "")
    if not receipt_ref.startswith("reviews/contextual_permission_rule_reviews/"):
        return bool(receipt_ref and rules.get("review_receipt_sha256"))
    receipt = _read_json_object(root / receipt_ref)
    receipt_sha256 = str(receipt.get("review_sha256") or "")
    if (
        not receipt
        or receipt_sha256 != rules.get("review_receipt_sha256")
        or receipt.get("review_ref") != receipt_ref
        or receipt.get("rules_ref") != rules_ref
        or receipt.get("reviewed_baseline_sha256")
        != rules.get("reviewed_baseline_sha256")
        or receipt.get("reviewed_node_ids")
        != [
            policy.get("node_id")
            for policy in rules.get("plan_node_policies") or []
            if isinstance(policy, dict)
        ]
    ):
        return False
    return receipt_sha256 == _canonical_digest(
        {
            key: value
            for key, value in receipt.items()
            if key != "review_sha256"
        }
    )
