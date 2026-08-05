from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from tests.qualification.contracts import (
    Counterexample,
    DomainModel,
    Finding,
    TransitionSpec,
    finding,
)


@dataclass(frozen=True)
class ExplorationResult:
    reachable_state_ids: tuple[str, ...]
    closed_nonterminal_components: tuple[tuple[str, ...], ...]
    findings: tuple[Finding, ...]
    counterexamples: tuple[Counterexample, ...]


def _outgoing(model: DomainModel) -> dict[str, tuple[TransitionSpec, ...]]:
    result: dict[str, list[TransitionSpec]] = {
        state.state_id: [] for state in model.states
    }
    for transition in model.transitions:
        if transition.source_state_id in result:
            result[transition.source_state_id].append(transition)
    return {
        key: tuple(sorted(items, key=lambda item: item.transition_id))
        for key, items in result.items()
    }


def _reachable(
    start: str,
    outgoing: dict[str, tuple[TransitionSpec, ...]],
) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for transition in outgoing.get(current, ()):
            if transition.target_state_id not in outgoing:
                continue
            if transition.target_state_id in seen:
                continue
            seen.add(transition.target_state_id)
            queue.append(transition.target_state_id)
    return seen


def _components(
    reachable: set[str],
    outgoing: dict[str, tuple[TransitionSpec, ...]],
) -> tuple[set[str], ...]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    result: list[set[str]] = []

    def visit(state_id: str) -> None:
        nonlocal index
        indexes[state_id] = index
        lowlinks[state_id] = index
        index += 1
        stack.append(state_id)
        on_stack.add(state_id)
        for transition in outgoing.get(state_id, ()):
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
        result.append(component)

    for state_id in sorted(reachable):
        if state_id not in indexes:
            visit(state_id)
    return tuple(result)


def _states_reaching_terminals(
    reachable: set[str],
    *,
    terminal_state_ids: set[str],
    outgoing: dict[str, tuple[TransitionSpec, ...]],
) -> set[str]:
    result = set(reachable & terminal_state_ids)
    changed = True
    while changed:
        changed = False
        for state_id in sorted(reachable - result):
            if any(
                transition.target_state_id in result
                for transition in outgoing.get(state_id, ())
            ):
                result.add(state_id)
                changed = True
    return result


def _closed_nonterminal(
    component: set[str],
    *,
    terminal_state_ids: set[str],
    outgoing: dict[str, tuple[TransitionSpec, ...]],
) -> bool:
    if component & terminal_state_ids:
        return False
    cyclic = len(component) > 1 or any(
        transition.target_state_id == state_id
        for state_id in component
        for transition in outgoing.get(state_id, ())
    )
    if not cyclic:
        return False
    return not any(
        transition.target_state_id not in component
        for state_id in component
        for transition in outgoing.get(state_id, ())
    )


def _shortest_path(
    start: str,
    targets: set[str],
    outgoing: dict[str, tuple[TransitionSpec, ...]],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    queue = deque([(start, (), (start,))])
    seen = {start}
    while queue:
        state_id, transition_path, state_path = queue.popleft()
        if state_id in targets:
            return state_id, transition_path, state_path
        for transition in outgoing.get(state_id, ()):
            target = transition.target_state_id
            if target in seen:
                continue
            seen.add(target)
            queue.append(
                (
                    target,
                    (*transition_path, transition.transition_id),
                    (*state_path, target),
                )
            )
    return start, (), (start,)


def _shortest_cycle(
    start: str,
    component: set[str],
    outgoing: dict[str, tuple[TransitionSpec, ...]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    queue = deque([(start, (), (start,))])
    best_depth = {start: 0}
    while queue:
        state_id, transition_path, state_path = queue.popleft()
        for transition in outgoing.get(state_id, ()):
            target = transition.target_state_id
            if target not in component:
                continue
            candidate_transitions = (*transition_path, transition.transition_id)
            candidate_states = (*state_path, target)
            if target == start:
                return candidate_transitions, candidate_states
            depth = len(candidate_transitions)
            if best_depth.get(target, depth + 1) <= depth:
                continue
            best_depth[target] = depth
            queue.append((target, candidate_transitions, candidate_states))
    return (), (start,)


def explore_domain(model: DomainModel) -> ExplorationResult:
    outgoing = _outgoing(model)
    terminal_ids = {item.terminal_id for item in model.terminals}
    terminal_state_ids = {
        state.state_id
        for state in model.states
        if state.terminal_id in terminal_ids
    }
    all_reachable: set[str] = set()
    component_keys: set[tuple[str, ...]] = set()
    findings: list[Finding] = []
    counterexamples: list[Counterexample] = []

    for start in sorted(model.supported_start_state_ids):
        if start not in outgoing:
            continue
        reachable = _reachable(start, outgoing)
        all_reachable.update(reachable)
        closed_for_start: set[str] = set()
        for component in _components(reachable, outgoing):
            if not _closed_nonterminal(
                component,
                terminal_state_ids=terminal_state_ids,
                outgoing=outgoing,
            ):
                continue
            key = tuple(sorted(component))
            closed_for_start.update(component)
            component_keys.add(key)
            entry, prefix_transitions, prefix_states = _shortest_path(
                start,
                component,
                outgoing,
            )
            cycle_transitions, cycle_states = _shortest_cycle(
                entry,
                component,
                outgoing,
            )
            transitions = (*prefix_transitions, *cycle_transitions)
            states = (*prefix_states, *cycle_states[1:])
            counterexample_id = f"counterexample.flow-livelock.{start}.{entry}"
            counterexamples.append(
                Counterexample(
                    counterexample_id=counterexample_id,
                    start_state_id=start,
                    transition_ids=transitions,
                    state_ids=states,
                    finding_code="FLOW-LIVELOCK",
                )
            )
            findings.append(
                finding(
                    "FLOW-LIVELOCK",
                    f"Supported start {start} reaches closed non-terminal component {key}.",
                    requirement="P2D-04",
                    evidence=(counterexample_id,),
                    suffix=f"{start}.{entry}",
                )
            )
        reaches_terminal = _states_reaching_terminals(
            reachable,
            terminal_state_ids=terminal_state_ids,
            outgoing=outgoing,
        )
        dead_ends = tuple(
            sorted(reachable - reaches_terminal - closed_for_start)
        )
        if dead_ends:
            target = dead_ends[0]
            _, transition_path, state_path = _shortest_path(
                start,
                {target},
                outgoing,
            )
            counterexample_id = f"counterexample.flow-blocked.{start}.{target}"
            counterexamples.append(
                Counterexample(
                    counterexample_id=counterexample_id,
                    start_state_id=start,
                    transition_ids=transition_path,
                    state_ids=state_path,
                    finding_code="FLOW-BLOCKED",
                )
            )
            findings.append(
                finding(
                    "FLOW-BLOCKED",
                    f"Supported start {start} reaches non-terminal dead end {target}.",
                    requirement="P2D-04",
                    evidence=(counterexample_id,),
                    suffix=f"{start}.{target}",
                )
            )

    findings_by_id = {item.finding_id: item for item in findings}
    counterexamples_by_id = {
        item.counterexample_id: item for item in counterexamples
    }
    return ExplorationResult(
        reachable_state_ids=tuple(sorted(all_reachable)),
        closed_nonterminal_components=tuple(sorted(component_keys)),
        findings=tuple(findings_by_id[key] for key in sorted(findings_by_id)),
        counterexamples=tuple(
            counterexamples_by_id[key] for key in sorted(counterexamples_by_id)
        ),
    )


__all__ = ["ExplorationResult", "explore_domain"]
