from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence

from tests.qualification.contracts import (
    DomainModel,
    Finding,
    HistoricalCapabilityInventory,
    HistoricalCapabilityRecord,
    ObservationEnvelope,
    ProductionReplayResult,
    StateVector,
    canonical_sha256,
    finding,
)


def validate_observation_envelope(
    model: DomainModel,
    envelope: ObservationEnvelope,
    *,
    expected_adapter_sha256: str | None = None,
) -> tuple[Finding, ...]:
    specs = {item.path: item for item in model.observation_fields}
    observed: dict[str, object] = {}
    findings: list[Finding] = []
    expected_inventory = canonical_sha256(model.observation_fields)
    if envelope.field_inventory_sha256 != expected_inventory:
        findings.append(
            finding(
                "OBSERVATION-INVENTORY-MISMATCH",
                "Observation field inventory identity does not match the model.",
                requirement="P2D-03",
                suffix=envelope.source_id,
            )
        )
    if expected_adapter_sha256 is not None and (
        envelope.adapter_sha256 != expected_adapter_sha256
    ):
        findings.append(
            finding(
                "OBSERVATION-ADAPTER-MISMATCH",
                "Observation adapter identity does not match the run manifest.",
                requirement="P2D-03",
                suffix=envelope.source_id,
            )
        )
    if len(envelope.payload_sha256) != 64:
        findings.append(
            finding(
                "OBSERVATION-PAYLOAD-IDENTITY-INVALID",
                "Observation payload identity is not a SHA-256 digest.",
                requirement="P2D-03",
                suffix=envelope.source_id,
            )
        )
    for item in envelope.fields:
        if item.path in observed:
            findings.append(
                finding(
                    "OBSERVATION-FIELD-DUPLICATE",
                    f"Observation field {item.path} appears more than once.",
                    requirement="P2D-03",
                    suffix=item.path.strip("/").replace("/", ".") or "root",
                )
            )
            continue
        observed[item.path] = item
        spec = specs.get(item.path)
        if spec is None:
            findings.append(
                finding(
                    "OBSERVATION-FIELD-UNKNOWN",
                    f"Observation field {item.path} is not declared.",
                    requirement="P2D-03",
                    suffix=item.path.strip("/").replace("/", ".") or "root",
                )
            )
            continue
        if item.provenance not in spec.allowed_provenance:
            findings.append(
                finding(
                    "OBSERVATION-PROVENANCE-INVALID",
                    f"Observation field {item.path} uses forbidden provenance {item.provenance}.",
                    requirement="P2D-01",
                    suffix=item.path.strip("/").replace("/", ".") or "root",
                )
            )
    for path, spec in specs.items():
        if spec.required and path not in observed:
            findings.append(
                finding(
                    "OBSERVATION-FIELD-MISSING",
                    f"Required observation field {path} is missing.",
                    requirement="P2D-03",
                    suffix=path.strip("/").replace("/", ".") or "root",
                )
            )
    return tuple(sorted(findings, key=lambda item: item.finding_id))


def detect_projection_collisions(
    model: DomainModel,
    observations: Sequence[tuple[ObservationEnvelope, StateVector]],
) -> tuple[Finding, ...]:
    specs = {item.path: item for item in model.observation_fields}
    equivalent_paths = {
        path
        for _, paths in model.equivalence_rules
        for path in paths
    }
    findings: list[Finding] = []
    for index, (left_envelope, left_state) in enumerate(observations):
        left = {item.path: item.canonical_value_json for item in left_envelope.fields}
        for right_envelope, right_state in observations[index + 1 :]:
            if (
                left_state.state_id != right_state.state_id
                or left_state.progress_signature != right_state.progress_signature
            ):
                continue
            right = {
                item.path: item.canonical_value_json
                for item in right_envelope.fields
            }
            differing = tuple(
                sorted(
                    path
                    for path, spec in specs.items()
                    if spec.classification in {"semantic", "identity_only"}
                    and left.get(path) != right.get(path)
                    and path not in equivalent_paths
                )
            )
            if not differing:
                continue
            suffix = ".".join(path.strip("/").replace("/", ".") for path in differing)
            findings.append(
                finding(
                    "PROJECTION-COLLISION",
                    f"Contract-relevant fields {differing} collapse to state {left_state.state_id}.",
                    requirement="P2D-03",
                    evidence=(left_envelope.source_id, right_envelope.source_id),
                    suffix=suffix,
                )
            )
    unique = {item.finding_id: item for item in findings}
    return tuple(unique[key] for key in sorted(unique))


def generate_exhaustive_cases(
    axes: Mapping[str, Sequence[object]],
) -> tuple[dict[str, object], ...]:
    names = tuple(sorted(axes))
    return tuple(
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(tuple(axes[name]) for name in names))
    )


def _pairs_for_case(
    names: tuple[str, ...],
    case: Mapping[str, object],
) -> set[tuple[str, str, str, str]]:
    return {
        (
            left,
            repr(case[left]),
            right,
            repr(case[right]),
        )
        for left_index, left in enumerate(names)
        for right in names[left_index + 1 :]
    }


def generate_pairwise_cases(
    axes: Mapping[str, Sequence[object]],
) -> tuple[dict[str, object], ...]:
    names = tuple(sorted(axes))
    exhaustive = generate_exhaustive_cases(axes)
    if len(names) < 2:
        return exhaustive
    uncovered = {
        pair
        for case in exhaustive
        for pair in _pairs_for_case(names, case)
    }
    selected: list[dict[str, object]] = []
    remaining = list(exhaustive)
    while uncovered:
        ranked = sorted(
            remaining,
            key=lambda case: (
                -len(_pairs_for_case(names, case) & uncovered),
                tuple(repr(case[name]) for name in names),
            ),
        )
        best = ranked[0]
        selected.append(best)
        uncovered -= _pairs_for_case(names, best)
        remaining.remove(best)
    return tuple(selected)


def missing_mcdc_conditions(
    conditions: Sequence[str],
    rows: Sequence[tuple[Mapping[str, bool], bool]],
) -> tuple[str, ...]:
    missing: list[str] = []
    for condition in conditions:
        witnessed = False
        for index, (left_values, left_decision) in enumerate(rows):
            for right_values, right_decision in rows[index + 1 :]:
                if left_decision == right_decision:
                    continue
                if left_values.get(condition) == right_values.get(condition):
                    continue
                if any(
                    left_values.get(other) != right_values.get(other)
                    for other in conditions
                    if other != condition
                ):
                    continue
                witnessed = True
                break
            if witnessed:
                break
        if not witnessed:
            missing.append(condition)
    return tuple(missing)


def validate_production_coverage(
    model: DomainModel,
    results: Sequence[ProductionReplayResult],
) -> tuple[Finding, ...]:
    specs = {item.replay_id: item for item in model.production_replays}
    result_by_id = {item.replay_id: item for item in results}
    findings: list[Finding] = []
    covered: set[str] = set()
    for replay_id, spec in specs.items():
        result = result_by_id.get(replay_id)
        if result is None or result.status not in {"passed", "infeasible"}:
            findings.append(
                finding(
                    "COVERAGE-INCOMPLETE",
                    f"Required replay {replay_id} did not complete.",
                    requirement="P2D-04",
                    suffix=replay_id,
                )
            )
            continue
        expected_status = (
            "passed" if spec.witness_kind == "production" else "infeasible"
        )
        if result.status != expected_status:
            findings.append(
                finding(
                    "COVERAGE-INCOMPLETE",
                    f"Replay {replay_id} did not satisfy {spec.witness_kind} witness status {expected_status}.",
                    requirement="P2D-04",
                    suffix=f"{replay_id}.witness-kind",
                )
            )
            continue
        if (
            spec.expected_terminal_id is not None
            and result.observed_terminal_id != spec.expected_terminal_id
        ):
            findings.append(
                finding(
                    "COVERAGE-INCOMPLETE",
                    f"Replay {replay_id} did not observe terminal {spec.expected_terminal_id}.",
                    requirement="P2D-04",
                    suffix=f"{replay_id}.terminal",
                )
            )
            continue
        declared = set(spec.covers_obligation_ids)
        observed = set(result.covered_obligation_ids)
        if not declared <= observed:
            findings.append(
                finding(
                    "COVERAGE-INCOMPLETE",
                    f"Replay {replay_id} omitted declared obligations {tuple(sorted(declared - observed))}.",
                    requirement="P2D-04",
                    suffix=f"{replay_id}.obligations",
                )
            )
        covered.update(observed)
    replay_kinds = {
        "supported_start",
        "transition",
        "terminal",
        "compatibility",
        "external_operator",
    }
    required = {
        item.obligation_id
        for item in model.obligations
        if item.required and item.kind in replay_kinds
    }
    if missing := required - covered:
        findings.append(
            finding(
                "COVERAGE-INCOMPLETE",
                f"Required obligations lack production evidence: {tuple(sorted(missing))}.",
                requirement="P2D-04",
                suffix="required-obligations",
            )
        )
    unknown = set(result_by_id) - set(specs)
    if unknown:
        findings.append(
            finding(
                "COVERAGE-INCOMPLETE",
                f"Undeclared replay results were supplied: {tuple(sorted(unknown))}.",
                requirement="P2D-04",
                suffix="undeclared-replays",
            )
        )
    unique = {item.finding_id: item for item in findings}
    return tuple(unique[key] for key in sorted(unique))


def _history_key(item: HistoricalCapabilityRecord) -> tuple[str, str]:
    return item.schema_version, item.capability_id


def reconcile_historical_inventory(
    declared: HistoricalCapabilityInventory,
    discovered: Sequence[HistoricalCapabilityRecord],
) -> tuple[Finding, ...]:
    declared_by_key = {_history_key(item): item for item in declared.records}
    discovered_by_key = {_history_key(item): item for item in discovered}
    mismatches: list[str] = []
    for key in sorted(set(declared_by_key) | set(discovered_by_key)):
        left = declared_by_key.get(key)
        right = discovered_by_key.get(key)
        if left is None or right is None:
            mismatches.append(f"{key[0]}:{key[1]}")
            continue
        if (
            left.disposition != right.disposition
            or left.migration_or_recovery_id != right.migration_or_recovery_id
        ):
            mismatches.append(f"{key[0]}:{key[1]}")
    if not mismatches:
        return ()
    return (
        finding(
            "HISTORICAL-INVENTORY-MISMATCH",
            f"Historical capability discovery disagrees for {tuple(mismatches)}.",
            requirement="P2D-06",
            suffix="reconciliation",
        ),
    )


__all__ = [
    "detect_projection_collisions",
    "generate_exhaustive_cases",
    "generate_pairwise_cases",
    "missing_mcdc_conditions",
    "reconcile_historical_inventory",
    "validate_observation_envelope",
    "validate_production_coverage",
]
