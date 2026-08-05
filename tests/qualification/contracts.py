from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Severity = Literal["info", "warning", "blocking"]
Verdict = Literal["pass", "fail", "invalid"]
TerminalKind = Literal[
    "ready",
    "safe_external_action_required",
    "quarantined",
]
FieldClassification = Literal[
    "semantic",
    "identity_only",
    "effect_only",
    "volatile",
    "ignored",
]
FieldProvenance = Literal[
    "raw_persisted_fact",
    "command_response_claim",
    "exact_identity",
    "attempted_effect",
    "volatile_metadata",
]


def _jsonable(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical value: {type(value)!r}")


def canonical_json(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class ObservationFieldSpec:
    path: str
    classification: FieldClassification
    allowed_provenance: tuple[FieldProvenance, ...]
    required: bool = True
    rationale: str | None = None


@dataclass(frozen=True)
class ObservationValue:
    path: str
    provenance: FieldProvenance
    canonical_value_json: str

    @classmethod
    def from_value(
        cls,
        *,
        path: str,
        provenance: FieldProvenance,
        value: object,
    ) -> "ObservationValue":
        return cls(
            path=path,
            provenance=provenance,
            canonical_value_json=canonical_json(value),
        )

    def decoded(self) -> object:
        return json.loads(self.canonical_value_json)


@dataclass(frozen=True)
class ObservationEnvelope:
    source_id: str
    source_kind: str
    payload_sha256: str
    field_inventory_sha256: str
    adapter_sha256: str
    fields: tuple[ObservationValue, ...]


@dataclass(frozen=True)
class StateVector:
    domain_id: str
    state_id: str
    semantic_axes: tuple[tuple[str, str], ...]
    progress_signature: tuple[str, ...]
    terminal_id: str | None = None
    root_blocker_ids: tuple[str, ...] = ()
    parent_identities: tuple[str, ...] = ()
    accepted_terminal: bool = False
    forbidden_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class TerminalSpec:
    terminal_id: str
    kind: TerminalKind
    ready: bool
    obligation_ids: tuple[str, ...] = ()
    machine_repair_transition_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransitionSpec:
    transition_id: str
    source_state_id: str
    target_state_id: str
    actor: str
    command_id: str | None = None
    required: bool = True
    advertised_recovery: bool = False
    compatibility_path_id: str | None = None
    recovery_rank_before: int | None = None
    recovery_rank_after: int | None = None
    allowed_effect_operations: tuple[str, ...] = ()
    typed_failure_outcomes: tuple[str, ...] = ()
    idempotency_required: bool = False


@dataclass(frozen=True)
class ObservedTransition:
    transition_id: str
    source_observation_id: str
    target_observation_id: str | None
    command_identity: str
    snapshot_identity: str | None
    evaluator_identity: str | None
    status: Literal["passed", "failed", "rejected", "interrupted"]
    effect_attempt_ids: tuple[str, ...] = ()
    receipt_identities: tuple[str, ...] = ()
    typed_failure: str | None = None


@dataclass(frozen=True)
class InvariantSpec:
    invariant_id: str
    requirement_ref: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class InvariantResult:
    invariant_id: str
    status: Literal["passed", "failed", "not_run"]
    evidence_id: str
    finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObligationSpec:
    obligation_id: str
    kind: str
    target_id: str
    required: bool = True


@dataclass(frozen=True)
class ObligationResult:
    obligation_id: str
    status: Literal["passed", "failed", "not_run", "infeasible"]
    evidence_id: str
    finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductionReplaySpec:
    replay_id: str
    runner_id: str
    covers_obligation_ids: tuple[str, ...]
    expected_terminal_id: str | None
    witness_kind: Literal["production", "infeasible", "quarantine"] = "production"


@dataclass(frozen=True)
class ProductionReplayResult:
    replay_id: str
    status: Literal["passed", "failed", "not_run", "infeasible"]
    observed_terminal_id: str | None
    covered_obligation_ids: tuple[str, ...]
    detail: str = ""


@dataclass(frozen=True)
class HistoricalCapabilityRecord:
    schema_version: str
    capability_id: str
    discovered_from: tuple[str, ...]
    disposition: Literal[
        "direct_support",
        "executable_migration",
        "quarantined",
    ]
    migration_or_recovery_id: str | None = None


@dataclass(frozen=True)
class HistoricalCapabilityInventory:
    source_sha256: tuple[tuple[str, str], ...]
    records: tuple[HistoricalCapabilityRecord, ...]


@dataclass(frozen=True)
class EffectCallsiteSpec:
    callsite_id: str
    source_ref: str
    line: int
    signature: str
    operation: str
    effect_class: str


@dataclass(frozen=True)
class EffectClassAuditSpec:
    effect_class: str
    disposition: Literal["present", "absent"]
    forbidden_static_prefixes: tuple[str, ...] = ()
    runtime_canary_id: str | None = None
    runtime_canary_operation: str | None = None
    rationale: str = ""


@dataclass(frozen=True)
class FaultCoverageCell:
    effect_operation: str
    injection_phase: Literal["before", "inside", "after"]
    applicability: Literal["required", "not_applicable"]
    fault_id: str | None = None
    rationale: str = ""


@dataclass(frozen=True)
class EffectSurfaceManifest:
    source_sha256: str
    operations: tuple[str, ...]
    allowed_read_roots: tuple[str, ...]
    allowed_write_roots: tuple[str, ...]
    absent_effect_classes: tuple[str, ...] = ()
    static_call_signatures: tuple[str, ...] = ()
    callsites: tuple[EffectCallsiteSpec, ...] = ()
    class_audits: tuple[EffectClassAuditSpec, ...] = ()
    fault_coverage: tuple[FaultCoverageCell, ...] = ()


@dataclass(frozen=True)
class EffectAttempt:
    transition_id: str
    operation: str
    effect_class: str
    scope: str
    ref: str
    outcome: Literal[
        "attempted",
        "completed",
        "blocked_before_invocation",
    ] = "attempted"
    canary_id: str | None = None


@dataclass(frozen=True)
class EffectClassAuditResult:
    effect_class: str
    static_status: Literal["passed", "failed", "not_run"]
    runtime_status: Literal["passed", "failed", "not_run"]
    canary_id: str | None
    observed_operation: str | None
    detail: str = ""


@dataclass(frozen=True)
class FaultSpec:
    fault_id: str
    effect_operation: str
    injection_point: str
    expected_terminal_kinds: tuple[str, ...]
    injection_phase: Literal["before", "inside", "after"] = "inside"
    fresh_instance_required: bool = True


@dataclass(frozen=True)
class FaultResult:
    fault_id: str
    status: Literal["passed", "failed", "not_run"]
    observed_terminal_kind: str
    detail: str = ""
    activated: bool = False
    execution_identity: str = ""


@dataclass(frozen=True)
class ConcurrencyScheduleSpec:
    schedule_id: str
    left_command_id: str
    right_command_id: str
    yield_point: str
    conflict_pair_id: str = ""
    fresh_instance_required: bool = True


@dataclass(frozen=True)
class ConcurrencyScheduleResult:
    schedule_id: str
    status: Literal["passed", "failed", "not_run"]
    observed_result: str
    detail: str = ""
    activated: bool = False
    execution_identity: str = ""


@dataclass(frozen=True)
class ConcurrencyConflictSpec:
    conflict_pair_id: str
    left_command_id: str
    right_command_id: str
    applicable_yield_points: tuple[str, ...]


@dataclass(frozen=True)
class MutationSpec:
    mutant_id: str
    mutation_site: str
    mutation_change: str
    obligation_id: str
    expected_finding_code: str
    expected_detection_mode: str = "finding"


@dataclass(frozen=True)
class MutationResult:
    mutant_id: str
    activated: bool
    status: Literal["killed", "survived", "crashed", "invalid"]
    observed_finding_codes: tuple[str, ...]
    detail: str = ""


@dataclass(frozen=True)
class Finding:
    finding_id: str
    code: str
    severity: Severity
    summary: str
    requirement_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Counterexample:
    counterexample_id: str
    start_state_id: str
    transition_ids: tuple[str, ...]
    state_ids: tuple[str, ...]
    finding_code: str


@dataclass(frozen=True)
class QualificationRunManifest:
    run_id: str
    phase1_prerequisite_sha256: str
    component_sha256: tuple[tuple[str, str], ...]
    deterministic_clock: str
    deterministic_seed: int


@dataclass(frozen=True)
class DomainModel:
    domain_id: str
    contract_version: str
    states: tuple[StateVector, ...]
    transitions: tuple[TransitionSpec, ...]
    supported_start_state_ids: tuple[str, ...]
    terminals: tuple[TerminalSpec, ...]
    observation_fields: tuple[ObservationFieldSpec, ...]
    obligations: tuple[ObligationSpec, ...]
    production_replays: tuple[ProductionReplaySpec, ...]
    historical_inventory: HistoricalCapabilityInventory
    effect_surface: EffectSurfaceManifest
    equivalence_rules: tuple[tuple[str, tuple[str, ...]], ...] = ()
    required_faults: tuple[FaultSpec, ...] = ()
    required_concurrency_schedules: tuple[ConcurrencyScheduleSpec, ...] = ()
    concurrency_conflicts: tuple[ConcurrencyConflictSpec, ...] = ()
    invariants: tuple[InvariantSpec, ...] = ()


@dataclass(frozen=True)
class QualificationReport:
    schema_version: str
    run_id: str
    run_manifest_sha256: str
    verdict: Verdict
    complete: bool
    phase1_prerequisite_sha256: str = ""
    run_manifest_component_sha256: tuple[tuple[str, str], ...] = ()
    findings: tuple[Finding, ...] = ()
    obligation_results: tuple[ObligationResult, ...] = ()
    replay_results: tuple[ProductionReplayResult, ...] = ()
    effect_class_results: tuple[EffectClassAuditResult, ...] = ()
    fault_results: tuple[FaultResult, ...] = ()
    concurrency_results: tuple[ConcurrencyScheduleResult, ...] = ()
    mutation_results: tuple[MutationResult, ...] = ()
    counterexamples: tuple[Counterexample, ...] = ()
    invariant_results: tuple[InvariantResult, ...] = ()
    unresolved_state_ids: tuple[str, ...] = ()
    coverage_inventory: tuple[tuple[str, str], ...] = ()
    telemetry: tuple[tuple[str, int], ...] = field(default_factory=tuple)


def finding(
    code: str,
    summary: str,
    *,
    requirement: str,
    evidence: tuple[str, ...] = (),
    suffix: str | None = None,
    severity: Severity = "blocking",
) -> Finding:
    stable_suffix = suffix or hashlib.sha256(summary.encode("utf-8")).hexdigest()[:12]
    return Finding(
        finding_id=f"{code.lower()}.{stable_suffix}",
        code=code,
        severity=severity,
        summary=summary,
        requirement_refs=(requirement,),
        evidence_refs=evidence,
    )


__all__ = [
    "ConcurrencyScheduleResult",
    "ConcurrencyScheduleSpec",
    "Counterexample",
    "DomainModel",
    "EffectAttempt",
    "EffectSurfaceManifest",
    "FaultResult",
    "FaultSpec",
    "Finding",
    "HistoricalCapabilityInventory",
    "HistoricalCapabilityRecord",
    "InvariantResult",
    "InvariantSpec",
    "MutationResult",
    "MutationSpec",
    "ObservationEnvelope",
    "ObservationFieldSpec",
    "ObservationValue",
    "ObservedTransition",
    "ObligationResult",
    "ObligationSpec",
    "ProductionReplayResult",
    "ProductionReplaySpec",
    "QualificationReport",
    "QualificationRunManifest",
    "StateVector",
    "TerminalSpec",
    "TransitionSpec",
    "canonical_json",
    "canonical_sha256",
    "file_sha256",
    "finding",
]
