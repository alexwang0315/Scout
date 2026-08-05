from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tests.qualification.contracts import canonical_sha256


RiskTier = Literal[0, 1, 2]
QualificationStatus = Literal["passed", "failed", "invalid", "not_applicable"]
AggregateVerdict = Literal["pass", "fail", "invalid"]


@dataclass(frozen=True)
class DashboardEntrypoint:
    entrypoint_id: str
    source_ref: str
    line: int
    symbol: str
    entrypoint_class: str
    registration_site: str
    reachable_target: str
    semantic_classification: str
    effect_classification: str
    disposition: str
    domain_id: str | None
    exclusion_evidence: str | None = None


@dataclass(frozen=True)
class DashboardExecutableEntrypointManifest:
    repository_identity: str
    roots: tuple[str, ...]
    entries: tuple[DashboardEntrypoint, ...]
    unresolved_dynamic_dispatch: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainRiskProfile:
    domain_id: str
    declared_tier: RiskTier
    runtime_safety_authority: bool = False
    privacy_sensitive: bool = False
    durable_publication: bool = False
    shared_authority_writer: bool = False
    external_effects: bool = False
    human_confirmation: bool = False
    background_execution: bool = False
    downstream_decision_impact: bool = False
    source_refs: tuple[str, ...] = ()

    @property
    def derived_minimum_tier(self) -> RiskTier:
        if self.runtime_safety_authority or self.shared_authority_writer:
            return 0
        if any(
            (
                self.privacy_sensitive,
                self.durable_publication,
                self.external_effects,
                self.human_confirmation,
                self.background_execution,
                self.downstream_decision_impact,
            )
        ):
            return 1
        return 2

    @property
    def valid(self) -> bool:
        return self.declared_tier <= self.derived_minimum_tier

    @property
    def identity(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True)
class NotApplicableWitness:
    witness_id: str
    domain_id: str
    obligation_id: str
    risk_profile_sha256: str
    absent_callsites_sha256: str
    executable_witness_id: str
    activated: bool
    observed_infeasible: bool


@dataclass(frozen=True)
class DashboardDomainSpec:
    domain_id: str
    risk_profile: DomainRiskProfile
    ui_routes: tuple[str, ...]
    api_route_prefixes: tuple[str, ...]
    production_source_refs: tuple[str, ...]
    persisted_capabilities: tuple[str, ...]
    fixture_classes: tuple[str, ...]
    observation_fields: tuple[str, ...]
    supported_start_states: tuple[str, ...]
    transitions: tuple[str, ...]
    terminals: tuple[str, ...]
    recovery_transitions: tuple[str, ...]
    decision_gate_kinds: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True)
class DependencyEdgeSpec:
    edge_id: str
    producer: str
    consumer: str
    producer_domain: str
    consumer_domain: str
    artifact_class: str
    join_fields: tuple[str, ...]
    freshness_rule: str
    invalidation_trigger: str
    recovery_transition: str
    authority_influence: str
    source_callsites: tuple[str, ...]
    shared_state: bool = True


@dataclass(frozen=True)
class DependencyCaseResult:
    case_id: str
    edge_id: str
    case_kind: str
    status: QualificationStatus
    observed_terminal: str
    producer_identity: str
    consumer_parent_identity: str | None
    activated: bool


@dataclass(frozen=True)
class AuthorityReceipt:
    subject_id: str
    subject_sha256: str
    capability_id: str
    generation: str
    actor: str
    policy_version: str
    evaluator_version: str
    scope: str
    idempotency_key: str


@dataclass(frozen=True)
class AuthorityBoundarySpec:
    boundary_id: str
    source_class: str
    sink_class: str
    allowed: bool
    requires_receipt: bool
    source_callsites: tuple[str, ...]


@dataclass(frozen=True)
class EffectOperation:
    operation_id: str
    domain_id: str
    normalized_operation: str
    state_affecting: bool
    source_ref: str
    line: int
    signature: str


@dataclass(frozen=True)
class EffectFaultCell:
    cell_id: str
    operation_id: str
    phase: Literal["before", "inside", "after"]
    applicability: Literal["required", "not_applicable"]
    witness_id: str | None = None


@dataclass(frozen=True)
class EffectFaultResult:
    cell_id: str
    status: QualificationStatus
    activated: bool
    process_identity: str
    workbench_identity: str
    observed_terminal: str


@dataclass(frozen=True)
class CommandResourceSpec:
    command_id: str
    domain_id: str
    entrypoint_id: str
    read_set: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    lock_set: tuple[str, ...] = ()
    journal_set: tuple[str, ...] = ()
    pointer_set: tuple[str, ...] = ()
    receipt_set: tuple[str, ...] = ()
    identity_set: tuple[str, ...] = ()
    source_callsites: tuple[str, ...] = ()
    replay_observations: tuple[str, ...] = ()

    @property
    def conflict_resources(self) -> frozenset[str]:
        return frozenset(
            (*self.write_set, *self.lock_set, *self.journal_set, *self.pointer_set,
             *self.receipt_set, *self.identity_set)
        )

    @property
    def observed_resources(self) -> frozenset[str]:
        return frozenset(
            (*self.read_set, *self.write_set, *self.lock_set, *self.journal_set,
             *self.pointer_set, *self.receipt_set, *self.identity_set)
        )


@dataclass(frozen=True)
class ConflictSchedule:
    schedule_id: str
    left_command_id: str
    right_command_id: str
    yield_point: str
    shared_resources: tuple[str, ...]


@dataclass(frozen=True)
class ConflictScheduleResult:
    schedule_id: str
    status: QualificationStatus
    activated: bool
    process_identity: str
    workbench_identity: str
    observed_result: str


@dataclass(frozen=True)
class WorkspaceInventoryEntry:
    path_digest: str
    entry_type: str
    device: int
    inode: int
    link_count: int
    size: int
    mtime_ns: int
    ctime_ns: int
    permitted_content_sha256: str | None
    disposition: str


@dataclass(frozen=True)
class WorkspaceInventorySnapshot:
    root_device: int
    root_inode: int
    generation_marker: str | None
    before_seal_sha256: str
    after_seal_sha256: str
    entries: tuple[WorkspaceInventoryEntry, ...]
    capability_dispositions: tuple[tuple[str, str], ...]
    findings: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True)
class Phase3Finding:
    finding_id: str
    code: str
    severity: Literal["blocking", "warning", "info"]
    summary: str
    requirement_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Phase3CaseResult:
    case_id: str
    category: str
    status: QualificationStatus
    activated: bool
    evidence_ref: str
    finding_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Phase3DomainReport:
    schema_version: str
    run_id: str
    aggregate_run_id: str
    domain_id: str
    source_manifest_sha256: str
    domain_model_sha256: str
    workspace_snapshot_sha256: str | None
    verdict: AggregateVerdict
    complete: bool
    cases: tuple[Phase3CaseResult, ...]
    findings: tuple[Phase3Finding, ...] = ()
    telemetry: tuple[tuple[str, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Phase3AggregateReport:
    schema_version: str
    run_id: str
    claim: Literal["construction", "release"]
    design_sha256: str
    phase2_report_sha256: str
    repository_identity: str
    source_manifest_sha256: str
    workspace_snapshot_sha256: str | None
    verdict: AggregateVerdict
    complete: bool
    required_domain_ids: tuple[str, ...]
    domain_report_sha256: tuple[tuple[str, str], ...]
    cases: tuple[Phase3CaseResult, ...]
    findings: tuple[Phase3Finding, ...] = ()
    component_sha256: tuple[tuple[str, str], ...] = ()
    telemetry: tuple[tuple[str, int], ...] = field(default_factory=tuple)


__all__ = [
    "AggregateVerdict",
    "AuthorityBoundarySpec",
    "AuthorityReceipt",
    "CommandResourceSpec",
    "ConflictSchedule",
    "ConflictScheduleResult",
    "DashboardDomainSpec",
    "DashboardEntrypoint",
    "DashboardExecutableEntrypointManifest",
    "DependencyCaseResult",
    "DependencyEdgeSpec",
    "DomainRiskProfile",
    "EffectFaultCell",
    "EffectFaultResult",
    "EffectOperation",
    "NotApplicableWitness",
    "Phase3AggregateReport",
    "Phase3CaseResult",
    "Phase3DomainReport",
    "Phase3Finding",
    "QualificationStatus",
    "RiskTier",
    "WorkspaceInventoryEntry",
    "WorkspaceInventorySnapshot",
]
