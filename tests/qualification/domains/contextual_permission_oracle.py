from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests.qualification.contextual_permission_phase1 import (
    PermissionQualificationState,
    extract_permission_state,
)
from tests.qualification.contracts import (
    DomainModel,
    ObservationEnvelope,
    ObservationValue,
    StateVector,
    canonical_sha256,
)
from tests.qualification.domains.contextual_permission_model import (
    IDENTITY_FIELD_NAMES,
    SEMANTIC_FIELD_NAMES,
)


class UnknownContextualPermissionObservation(ValueError):
    """Raised rather than coercing an undeclared semantic state."""


@dataclass(frozen=True)
class OracleObservation:
    envelope: ObservationEnvelope
    state: StateVector


def envelope_from_independent_state(
    state: PermissionQualificationState,
    *,
    source_id: str,
    adapter_sha256: str,
    model: DomainModel,
) -> ObservationEnvelope:
    fields = [
        ObservationValue.from_value(
            path=f"/{name}",
            provenance="raw_persisted_fact",
            value=getattr(state, name),
        )
        for name in SEMANTIC_FIELD_NAMES
    ]
    for name in IDENTITY_FIELD_NAMES:
        value = getattr(state, name)
        if value is None:
            continue
        fields.append(
            ObservationValue.from_value(
                path=f"/{name}",
                provenance="exact_identity",
                value=value,
            )
        )
    if state.forbidden_effects:
        fields.append(
            ObservationValue.from_value(
                path="/forbidden_effects",
                provenance="attempted_effect",
                value=state.forbidden_effects,
            )
        )
    return ObservationEnvelope(
        source_id=source_id,
        source_kind="isolated_workspace",
        payload_sha256=canonical_sha256(state),
        field_inventory_sha256=canonical_sha256(model.observation_fields),
        adapter_sha256=adapter_sha256,
        fields=tuple(sorted(fields, key=lambda item: item.path)),
    )


def project_contextual_permission_state(
    envelope: ObservationEnvelope,
    *,
    model: DomainModel,
) -> StateVector:
    observed = {
        item.path.removeprefix("/"): item.canonical_value_json
        for item in envelope.fields
    }
    missing = tuple(
        name for name in SEMANTIC_FIELD_NAMES if name not in observed
    )
    if missing:
        raise UnknownContextualPermissionObservation(
            f"semantic fields are missing: {missing}"
        )
    semantic_axes = tuple(
        (name, observed[name]) for name in SEMANTIC_FIELD_NAMES
    )
    matches = tuple(
        state for state in model.states if state.semantic_axes == semantic_axes
    )
    if len(matches) != 1:
        raise UnknownContextualPermissionObservation(
            "observation must map to exactly one declared state; "
            f"matched={tuple(item.state_id for item in matches)}"
        )
    return matches[0]


def observe_isolated_project(
    project_root: Path,
    *,
    source_id: str,
    adapter_sha256: str,
    model: DomainModel,
) -> OracleObservation:
    independent = extract_permission_state(
        Path(project_root),
        state_id="untrusted-observation-label",
    )
    envelope = envelope_from_independent_state(
        independent,
        source_id=source_id,
        adapter_sha256=adapter_sha256,
        model=model,
    )
    return OracleObservation(
        envelope=envelope,
        state=project_contextual_permission_state(envelope, model=model),
    )


__all__ = [
    "OracleObservation",
    "UnknownContextualPermissionObservation",
    "envelope_from_independent_state",
    "observe_isolated_project",
    "project_contextual_permission_state",
]
