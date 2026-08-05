from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from tests.qualification.contracts import (
    DomainModel,
    EffectSurfaceManifest,
    HistoricalCapabilityInventory,
    ObservationFieldSpec,
    ObligationSpec,
    ProductionReplaySpec,
    StateVector,
    TerminalSpec,
    TransitionSpec,
    canonical_json,
)


SEMANTIC_FIELD_NAMES = (
    "baseline_capability",
    "baseline_lifecycle",
    "required_inputs",
    "baseline_review_binding",
    "migration",
    "projection",
    "policy_review",
    "rebuild_admission",
    "outcome",
    "root_blocker_ids",
)

IDENTITY_FIELD_NAMES = (
    "artifact_identity",
    "parent_identities",
    "command_snapshot_sha256",
    "evaluator_version",
)


def _field_value(item: dict[str, object], name: str) -> str:
    value = item.get(name)
    if name in {"root_blocker_ids", "parent_identities"}:
        value = sorted(str(entry) for entry in value or ())
    return canonical_json(value)


def _shortest_path_transitions(
    start: str,
    *,
    ready_state_id: str,
    transitions: tuple[TransitionSpec, ...],
) -> tuple[str, ...]:
    outgoing: dict[str, list[TransitionSpec]] = {}
    for transition in transitions:
        outgoing.setdefault(transition.source_state_id, []).append(transition)
    queue = deque([(start, ())])
    visited = {start}
    while queue:
        state_id, path = queue.popleft()
        if state_id == ready_state_id:
            return path
        for transition in sorted(
            outgoing.get(state_id, ()),
            key=lambda item: item.transition_id,
        ):
            if transition.target_state_id in visited:
                continue
            visited.add(transition.target_state_id)
            queue.append(
                (
                    transition.target_state_id,
                    (*path, transition.transition_id),
                )
            )
    raise ValueError(f"supported start has no ready path: {start}")


def build_contextual_permission_model(
    *,
    catalog_path: Path,
    replay_manifest_path: Path,
    historical_inventory: HistoricalCapabilityInventory,
    effect_surface: EffectSurfaceManifest,
) -> DomainModel:
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    replay_manifest = json.loads(
        Path(replay_manifest_path).read_text(encoding="utf-8")
    )
    terminals = (
        TerminalSpec("terminal.ready", "ready", True),
        TerminalSpec(
            "terminal.quarantined-unsupported",
            "quarantined",
            False,
            obligation_ids=("operator:replace-or-export-unsupported",),
        ),
    )
    terminal_by_state = {
        "qualified-ready": "terminal.ready",
        "quarantined-unsupported": "terminal.quarantined-unsupported",
    }
    states = tuple(
        StateVector(
            domain_id="contextual_permission",
            state_id=str(item["state_id"]),
            semantic_axes=tuple(
                (name, _field_value(item, name))
                for name in SEMANTIC_FIELD_NAMES
            ),
            progress_signature=tuple(
                _field_value(item, name) for name in SEMANTIC_FIELD_NAMES
            ),
            terminal_id=terminal_by_state.get(str(item["state_id"])),
            root_blocker_ids=tuple(
                sorted(
                    str(value)
                    for value in item.get("root_blocker_ids") or ()
                )
            ),
            accepted_terminal=str(item["state_id"]) in terminal_by_state,
        )
        for item in catalog["states"]
    )
    transitions = tuple(
        TransitionSpec(
            transition_id=str(item["transition_id"]),
            source_state_id=str(item["source_state_id"]),
            target_state_id=str(item["target_state_id"]),
            actor=str(item["actor"]),
            command_id=f"contextual_permission.{item['transition_id']}",
            advertised_recovery=bool(item.get("advertised_as_recovery")),
            recovery_rank_before=item.get("recovery_rank_before"),
            recovery_rank_after=item.get("recovery_rank_after"),
            compatibility_path_id=(
                "compatibility.legacy-to-ref-gpx"
                if "proposal-inputs" in str(item["transition_id"])
                else None
            ),
        )
        for item in catalog["transitions"]
    )
    transitions = (
        *transitions,
        TransitionSpec(
            transition_id="author-proposal-from-no-baseline",
            source_state_id="no-baseline",
            target_state_id="proposal-migration-candidate",
            actor="human_decision",
            command_id="contextual_permission.author-proposal-from-no-baseline",
        ),
    )
    supported_starts = tuple(str(item) for item in catalog["supported_start_state_ids"])
    obligations = (
        *(
            ObligationSpec(f"start:{state_id}", "supported_start", state_id)
            for state_id in supported_starts
        ),
        *(
            ObligationSpec(
                f"transition:{transition.transition_id}",
                "transition",
                transition.transition_id,
            )
            for transition in transitions
        ),
        ObligationSpec("terminal:ready", "terminal", "terminal.ready"),
        ObligationSpec(
            "terminal:quarantined-unsupported",
            "terminal",
            "terminal.quarantined-unsupported",
        ),
        ObligationSpec(
            "operator:replace-or-export-unsupported",
            "external_operator",
            "unsupported-baseline",
        ),
        ObligationSpec(
            "compatibility:legacy-to-ref-gpx",
            "compatibility",
            "legacy_sparse.v1->ref_gpx_proposal.v1",
        ),
    )
    production_replays: list[ProductionReplaySpec] = []
    replay_entries = replay_manifest["replays"]
    for start in supported_starts:
        if start not in replay_entries:
            raise ValueError(f"supported start lacks replay declaration: {start}")
        path = _shortest_path_transitions(
            start,
            ready_state_id="qualified-ready",
            transitions=transitions,
        )
        covered = {
            f"start:{start}",
            "terminal:ready",
            *(f"transition:{transition_id}" for transition_id in path),
        }
        if any("proposal-inputs" in transition_id for transition_id in path):
            covered.add("compatibility:legacy-to-ref-gpx")
        production_replays.append(
            ProductionReplaySpec(
                replay_id=f"replay.start.{start}",
                runner_id=str(replay_entries[start]["test_node_id"]),
                covers_obligation_ids=tuple(sorted(covered)),
                expected_terminal_id="terminal.ready",
            )
        )
    production_replays.extend(
        (
            ProductionReplaySpec(
                replay_id="replay.transition.author-legacy-candidate",
                runner_id="phase2.transition.author-legacy-candidate",
                covers_obligation_ids=("transition:author-legacy-candidate",),
                expected_terminal_id=None,
            ),
            ProductionReplaySpec(
                replay_id=(
                    "replay.transition.provide-proposal-inputs-from-candidate"
                ),
                runner_id=(
                    "phase2.transition.provide-proposal-inputs-from-candidate"
                ),
                covers_obligation_ids=(
                    "transition:provide-proposal-inputs-from-candidate",
                ),
                expected_terminal_id=None,
            ),
        )
    )
    production_replays.append(
        ProductionReplaySpec(
            replay_id="replay.quarantine.unsupported",
            runner_id="quarantine.unsupported.explicit-witness",
            covers_obligation_ids=(
                "transition:invalidate-invariant-breach",
                "transition:quarantine-corrupt-artifact",
                "terminal:quarantined-unsupported",
                "operator:replace-or-export-unsupported",
            ),
            expected_terminal_id="terminal.quarantined-unsupported",
            witness_kind="quarantine",
        )
    )
    observation_fields = (
        *(
            ObservationFieldSpec(
                path=f"/{name}",
                classification="semantic",
                allowed_provenance=("raw_persisted_fact",),
            )
            for name in SEMANTIC_FIELD_NAMES
        ),
        *(
            ObservationFieldSpec(
                path=f"/{name}",
                classification="identity_only",
                allowed_provenance=("exact_identity",),
                required=False,
            )
            for name in IDENTITY_FIELD_NAMES
        ),
        ObservationFieldSpec(
            path="/forbidden_effects",
            classification="effect_only",
            allowed_provenance=("attempted_effect",),
            required=False,
        ),
    )
    return DomainModel(
        domain_id="contextual_permission",
        contract_version="contextual-permission.qualification.v2",
        states=states,
        transitions=transitions,
        supported_start_state_ids=supported_starts,
        terminals=terminals,
        observation_fields=observation_fields,
        obligations=tuple(obligations),
        production_replays=tuple(production_replays),
        historical_inventory=historical_inventory,
        effect_surface=effect_surface,
        equivalence_rules=(
            (
                "equivalence.isomorphic-isolated-workspace-identities",
                (
                    "/artifact_identity",
                    "/parent_identities",
                    "/command_snapshot_sha256",
                ),
            ),
        ),
    )


__all__ = [
    "IDENTITY_FIELD_NAMES",
    "SEMANTIC_FIELD_NAMES",
    "build_contextual_permission_model",
]
