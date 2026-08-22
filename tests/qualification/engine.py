from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from tests.qualification.contracts import (
    ConcurrencyScheduleResult,
    DomainModel,
    EffectAttempt,
    EffectCallsiteSpec,
    EffectClassAuditResult,
    FaultResult,
    Finding,
    HistoricalCapabilityRecord,
    InvariantResult,
    MutationResult,
    MutationSpec,
    ObservationEnvelope,
    ObligationResult,
    ProductionReplayResult,
    QualificationReport,
    QualificationRunManifest,
    StateVector,
    canonical_sha256,
    finding,
)
from tests.qualification.coverage import (
    detect_projection_collisions,
    reconcile_historical_inventory,
    validate_observation_envelope,
    validate_production_coverage,
)
from tests.qualification.effects import (
    validate_effect_attempts,
    validate_effect_class_results,
    validate_static_effect_surface,
)
from tests.qualification.explorer import explore_domain


@dataclass(frozen=True)
class EvidenceBundle:
    observations: tuple[tuple[ObservationEnvelope, StateVector], ...] = ()
    obligation_results: tuple[ObligationResult, ...] = ()
    replay_results: tuple[ProductionReplayResult, ...] = ()
    discovered_history: tuple[HistoricalCapabilityRecord, ...] = ()
    effect_attempts: tuple[EffectAttempt, ...] = ()
    effect_class_results: tuple[EffectClassAuditResult, ...] = ()
    fault_results: tuple[FaultResult, ...] = ()
    concurrency_results: tuple[ConcurrencyScheduleResult, ...] = ()
    mutation_specs: tuple[MutationSpec, ...] = ()
    mutation_results: tuple[MutationResult, ...] = ()
    static_effect_calls: tuple[str, ...] = ()
    static_effect_callsites: tuple[EffectCallsiteSpec, ...] = ()
    additional_findings: tuple[Finding, ...] = ()
    invariant_results: tuple[InvariantResult, ...] = ()


_REQUIRED_MANIFEST_COMPONENTS = {
    "engine",
    "model",
    "oracle",
    "adapter",
    "production",
    "fixtures",
    "history",
    "effects",
    "bounds",
    "decisions",
    "faults",
    "concurrency",
    "mutants",
    "configuration",
}


def _duplicate_values(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def validate_domain_model(model: DomainModel) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    state_ids = tuple(item.state_id for item in model.states)
    transition_ids = tuple(item.transition_id for item in model.transitions)
    terminal_ids = tuple(item.terminal_id for item in model.terminals)
    obligation_ids = tuple(item.obligation_id for item in model.obligations)
    invariant_ids = tuple(item.invariant_id for item in model.invariants)
    replay_ids = tuple(item.replay_id for item in model.production_replays)
    for kind, values in (
        ("state", state_ids),
        ("transition", transition_ids),
        ("terminal", terminal_ids),
        ("obligation", obligation_ids),
        ("replay", replay_ids),
        ("invariant", invariant_ids),
    ):
        for duplicate in _duplicate_values(values):
            findings.append(
                finding(
                    "MODEL-DUPLICATE-ID",
                    f"Duplicate {kind} ID: {duplicate}.",
                    requirement="P2D-03",
                    suffix=f"{kind}.{duplicate}",
                )
            )
    state_id_set = set(state_ids)
    terminal_id_set = set(terminal_ids)
    transition_id_set = set(transition_ids)
    obligation_id_set = set(obligation_ids)
    for transition in model.transitions:
        for relation, state_id in (
            ("source", transition.source_state_id),
            ("target", transition.target_state_id),
        ):
            if state_id not in state_id_set:
                findings.append(
                    finding(
                        "MODEL-UNKNOWN-STATE",
                        f"Transition {transition.transition_id} has unknown {relation} state {state_id}.",
                        requirement="P2D-03",
                        suffix=f"{transition.transition_id}.{relation}",
                    )
                )
    for start in model.supported_start_state_ids:
        if start not in state_id_set:
            findings.append(
                finding(
                    "MODEL-UNKNOWN-STATE",
                    f"Supported start {start} is not declared.",
                    requirement="P2D-03",
                    suffix=f"start.{start}",
                )
            )
    for state in model.states:
        if state.terminal_id is not None and state.terminal_id not in terminal_id_set:
            findings.append(
                finding(
                    "MODEL-UNKNOWN-TERMINAL",
                    f"State {state.state_id} references unknown terminal {state.terminal_id}.",
                    requirement="P2D-03",
                    suffix=state.state_id,
                )
            )
        if state.accepted_terminal != (state.terminal_id is not None):
            findings.append(
                finding(
                    "STATE-TERMINAL-MISMATCH",
                    f"State {state.state_id} has inconsistent terminal metadata.",
                    requirement="P2D-02",
                    suffix=state.state_id,
                )
            )
        if state.root_blocker_ids and state.terminal_id is None and not any(
            transition.source_state_id == state.state_id
            for transition in model.transitions
        ):
            findings.append(
                finding(
                    "ROOT-BLOCKER-UNRECOVERABLE",
                    f"State {state.state_id} has root blockers but no recovery or quarantine.",
                    requirement="P2D-03",
                    suffix=state.state_id,
                )
            )
    for terminal in model.terminals:
        reasons: list[str] = []
        if terminal.kind == "ready":
            if not terminal.ready:
                reasons.append("ready kind has ready=false")
            if terminal.obligation_ids:
                reasons.append("ready terminal has outstanding obligations")
        else:
            if terminal.ready:
                reasons.append("non-ready kind has ready=true")
            if terminal.machine_repair_transition_ids:
                reasons.append("non-ready terminal exposes machine repair")
        unknown_repairs = set(terminal.machine_repair_transition_ids) - transition_id_set
        if unknown_repairs:
            reasons.append(f"unknown machine repairs {tuple(sorted(unknown_repairs))}")
        unknown_obligations = set(terminal.obligation_ids) - obligation_id_set
        if unknown_obligations:
            reasons.append(
                f"unknown obligations {tuple(sorted(unknown_obligations))}"
            )
        if reasons:
            findings.append(
                finding(
                    "TERMINAL-INVALID",
                    f"Terminal {terminal.terminal_id} is invalid: {', '.join(reasons)}.",
                    requirement="P2D-02",
                    suffix=terminal.terminal_id,
                )
            )
    state_by_id = {item.state_id: item for item in model.states}
    for transition in model.transitions:
        if transition.advertised_recovery:
            if (
                transition.recovery_rank_before is None
                or transition.recovery_rank_after is None
                or transition.recovery_rank_after >= transition.recovery_rank_before
            ):
                findings.append(
                    finding(
                        "RECOVERY-RANK-INVALID",
                        f"Advertised recovery {transition.transition_id} does not lower its rank.",
                        requirement="P2D-03",
                        suffix=transition.transition_id,
                    )
                )
            source = state_by_id.get(transition.source_state_id)
            target = state_by_id.get(transition.target_state_id)
            if source is not None and target is not None and (
                source.progress_signature == target.progress_signature
            ):
                findings.append(
                    finding(
                        "RECOVERY-NO-PROGRESS",
                        f"Advertised recovery {transition.transition_id} changes no semantic progress.",
                        requirement="P2D-03",
                        suffix=transition.transition_id,
                    )
                )
    field_paths = tuple(item.path for item in model.observation_fields)
    for duplicate in _duplicate_values(field_paths):
        findings.append(
            finding(
                "MODEL-DUPLICATE-ID",
                f"Duplicate observation field path: {duplicate}.",
                requirement="P2D-03",
                suffix=f"field.{duplicate.strip('/').replace('/', '.')}",
            )
        )
    for spec in model.observation_fields:
        if spec.classification == "ignored" and not spec.rationale:
            findings.append(
                finding(
                    "OBSERVATION-FIELD-INVALID",
                    f"Ignored observation field {spec.path} has no rationale.",
                    requirement="P2D-03",
                    suffix=spec.path.strip("/").replace("/", "."),
                )
            )
        if (
            spec.classification in {"semantic", "identity_only"}
            and "command_response_claim" in spec.allowed_provenance
        ):
            findings.append(
                finding(
                    "ORACLE-CONTAMINATION",
                    f"Contract-relevant field {spec.path} accepts a production response claim.",
                    requirement="P2D-01",
                    suffix=spec.path.strip("/").replace("/", "."),
                )
            )
    declared_paths = set(field_paths)
    equivalence_ids = tuple(item[0] for item in model.equivalence_rules)
    for duplicate in _duplicate_values(equivalence_ids):
        findings.append(
            finding(
                "MODEL-DUPLICATE-ID",
                f"Duplicate equivalence rule ID: {duplicate}.",
                requirement="P2D-03",
                suffix=f"equivalence.{duplicate}",
            )
        )
    for rule_id, paths in model.equivalence_rules:
        unknown_paths = set(paths) - declared_paths
        if not paths or unknown_paths:
            findings.append(
                finding(
                    "EQUIVALENCE-RULE-INVALID",
                    f"Equivalence rule {rule_id} has unknown or empty paths: {tuple(sorted(unknown_paths))}.",
                    requirement="P2D-03",
                    suffix=rule_id,
                )
            )
    if not model.effect_surface.operations:
        findings.append(
            finding(
                "EFFECT-SURFACE-INCOMPLETE",
                "The effect surface declares no operations.",
                requirement="P2D-07",
                suffix="empty",
            )
        )
    operation_set = set(model.effect_surface.operations)
    for duplicate in _duplicate_values(model.effect_surface.operations):
        findings.append(
            finding(
                "MODEL-DUPLICATE-ID",
                f"Duplicate effect operation: {duplicate}.",
                requirement="P2D-07",
                suffix=f"effect-operation.{duplicate}",
            )
        )
    callsite_ids = tuple(item.callsite_id for item in model.effect_surface.callsites)
    for duplicate in _duplicate_values(callsite_ids):
        findings.append(
            finding(
                "MODEL-DUPLICATE-ID",
                f"Duplicate effect callsite ID: {duplicate}.",
                requirement="P2D-07",
                suffix=f"effect-callsite.{duplicate}",
            )
        )
    invalid_callsites = tuple(
        sorted(
            item.callsite_id
            for item in model.effect_surface.callsites
            if item.operation not in operation_set
            or item.operation == "unclassified"
            or item.effect_class == "unclassified"
            or item.line <= 0
        )
    )
    if invalid_callsites:
        findings.append(
            finding(
                "EFFECT-SURFACE-INCOMPLETE",
                f"Effect callsites are unclassified or undeclared: {invalid_callsites}.",
                requirement="P2D-07",
                suffix="model-callsite-reconciliation",
            )
        )
    class_audit_ids = tuple(
        item.effect_class for item in model.effect_surface.class_audits
    )
    invalid_class_audits = tuple(
        sorted(
            item.effect_class
            for item in model.effect_surface.class_audits
            if item.disposition != "absent"
            or not item.forbidden_static_prefixes
            or not item.runtime_canary_id
            or not item.runtime_canary_operation
            or not item.rationale
        )
    )
    if (
        set(class_audit_ids) != set(model.effect_surface.absent_effect_classes)
        or _duplicate_values(class_audit_ids)
        or invalid_class_audits
    ):
        findings.append(
            finding(
                "EFFECT-SURFACE-INCOMPLETE",
                "Absent effect classes lack an exact static audit and runtime canary contract.",
                requirement="P2D-07",
                suffix="model-absent-class-audits",
            )
        )
    if model.effect_surface.fault_coverage:
        phases = {"before", "inside", "after"}
        expected_cells = {
            (operation, phase)
            for operation in model.effect_surface.operations
            for phase in phases
        }
        actual_cells = {
            (item.effect_operation, item.injection_phase)
            for item in model.effect_surface.fault_coverage
        }
        cell_keys = tuple(
            f"{item.effect_operation}:{item.injection_phase}"
            for item in model.effect_surface.fault_coverage
        )
        required_fault_by_id = {
            item.fault_id: item for item in model.required_faults
        }
        invalid_cells = []
        referenced_fault_ids = set()
        for cell in model.effect_surface.fault_coverage:
            if cell.applicability == "required":
                spec = required_fault_by_id.get(cell.fault_id or "")
                if (
                    spec is None
                    or spec.effect_operation != cell.effect_operation
                    or spec.injection_phase != cell.injection_phase
                    or cell.rationale
                ):
                    invalid_cells.append(
                        f"{cell.effect_operation}:{cell.injection_phase}"
                    )
                if cell.fault_id:
                    referenced_fault_ids.add(cell.fault_id)
            elif cell.fault_id is not None or not cell.rationale:
                invalid_cells.append(
                    f"{cell.effect_operation}:{cell.injection_phase}"
                )
        if (
            expected_cells != actual_cells
            or _duplicate_values(cell_keys)
            or invalid_cells
            or referenced_fault_ids != set(required_fault_by_id)
        ):
            findings.append(
                finding(
                    "FAULT-MATRIX-INCOMPLETE",
                    "Effect-operation by fault-phase coverage is incomplete or inconsistent.",
                    requirement="P2D-07",
                    suffix="model-fault-matrix",
                )
            )
    if model.concurrency_conflicts:
        pair_by_id = {
            item.conflict_pair_id: item for item in model.concurrency_conflicts
        }
        expected_schedule_keys = {
            (pair.conflict_pair_id, yield_point)
            for pair in model.concurrency_conflicts
            for yield_point in pair.applicable_yield_points
        }
        actual_schedule_keys = {
            (item.conflict_pair_id, item.yield_point)
            for item in model.required_concurrency_schedules
        }
        invalid_schedules = tuple(
            sorted(
                item.schedule_id
                for item in model.required_concurrency_schedules
                if (
                    (pair := pair_by_id.get(item.conflict_pair_id)) is None
                    or item.left_command_id != pair.left_command_id
                    or item.right_command_id != pair.right_command_id
                )
            )
        )
        if (
            len(pair_by_id) != len(model.concurrency_conflicts)
            or expected_schedule_keys != actual_schedule_keys
            or len(actual_schedule_keys) != len(model.required_concurrency_schedules)
            or invalid_schedules
        ):
            findings.append(
                finding(
                    "CONCURRENCY-MATRIX-INCOMPLETE",
                    "Conflicting-command by applicable-yield schedule matrix is incomplete.",
                    requirement="P2D-07",
                    suffix="model-concurrency-matrix",
                )
            )
    return tuple(sorted(findings, key=lambda item: item.finding_id))


def validate_run_manifest(
    model: DomainModel,
    manifest: QualificationRunManifest,
) -> tuple[Finding, ...]:
    components = dict(manifest.component_sha256)
    reasons: list[str] = []
    if len(components) != len(manifest.component_sha256):
        reasons.append("duplicate component identities")
    missing = _REQUIRED_MANIFEST_COMPONENTS - set(components)
    if missing:
        reasons.append(f"missing components {tuple(sorted(missing))}")
    if components.get("model") != canonical_sha256(model):
        reasons.append("model hash mismatch")
    if components.get("history") != canonical_sha256(model.historical_inventory):
        reasons.append("historical inventory hash mismatch")
    if components.get("effects") != canonical_sha256(model.effect_surface):
        reasons.append("effect surface hash mismatch")
    invalid_component_hashes = tuple(
        sorted(name for name, digest in components.items() if len(digest) != 64)
    )
    if invalid_component_hashes:
        reasons.append(f"invalid component hashes {invalid_component_hashes}")
    if not manifest.phase1_prerequisite_sha256 or len(
        manifest.phase1_prerequisite_sha256
    ) != 64:
        reasons.append("invalid Phase 1 prerequisite identity")
    if not reasons:
        return ()
    return (
        finding(
            "RUN-MANIFEST-MISMATCH",
            f"Qualification run manifest is invalid: {', '.join(reasons)}.",
            requirement="P2D-09",
            suffix=manifest.run_id,
        ),
    )


def _validate_obligations(
    model: DomainModel,
    results: Sequence[ObligationResult],
) -> tuple[Finding, ...]:
    result_by_id = {item.obligation_id: item for item in results}
    missing = tuple(
        sorted(
            item.obligation_id
            for item in model.obligations
            if item.required
            and (
                item.obligation_id not in result_by_id
                or result_by_id[item.obligation_id].status
                not in {"passed", "infeasible"}
            )
        )
    )
    if not missing:
        return ()
    return (
        finding(
            "COVERAGE-INCOMPLETE",
            f"Required qualification obligations are incomplete: {missing}.",
            requirement="P2D-04",
            suffix="obligation-results",
        ),
    )


def _validate_faults(
    model: DomainModel,
    results: Sequence[FaultResult],
) -> tuple[Finding, ...]:
    result_by_id = {item.fault_id: item for item in results}
    expected_ids = {item.fault_id for item in model.required_faults}
    spec_by_id = {item.fault_id: item for item in model.required_faults}
    incomplete = {
        fault_id
        for fault_id in expected_ids
        if fault_id not in result_by_id or result_by_id[fault_id].status != "passed"
    }
    incomplete.update(item.fault_id for item in results if item.status != "passed")
    incomplete.update(
        item.fault_id
        for item in results
        if item.fault_id in spec_by_id
        and item.status == "passed"
        and item.observed_terminal_kind
        not in spec_by_id[item.fault_id].expected_terminal_kinds
    )
    incomplete.update(
        item.fault_id
        for item in results
        if item.fault_id in spec_by_id
        and (
            not item.activated
            or (
                spec_by_id[item.fault_id].fresh_instance_required
                and not item.execution_identity
            )
        )
    )
    fresh_identities = [
        item.execution_identity
        for item in results
        if item.fault_id in spec_by_id
        and spec_by_id[item.fault_id].fresh_instance_required
        and item.execution_identity
    ]
    if len(set(fresh_identities)) != len(fresh_identities):
        incomplete.update(
            item.fault_id
            for item in results
            if item.fault_id in spec_by_id
            and spec_by_id[item.fault_id].fresh_instance_required
        )
    if not incomplete:
        return ()
    return (
        finding(
            "FAULT-INCOMPLETE",
            f"Fault obligations are incomplete: {tuple(sorted(incomplete))}.",
            requirement="P2D-07",
            suffix="fault-results",
        ),
    )


def _validate_concurrency(
    model: DomainModel,
    results: Sequence[ConcurrencyScheduleResult],
) -> tuple[Finding, ...]:
    result_by_id = {item.schedule_id: item for item in results}
    expected_ids = {
        item.schedule_id for item in model.required_concurrency_schedules
    }
    incomplete = {
        schedule_id
        for schedule_id in expected_ids
        if schedule_id not in result_by_id
        or result_by_id[schedule_id].status != "passed"
    }
    incomplete.update(
        item.schedule_id for item in results if item.status != "passed"
    )
    spec_by_id = {
        item.schedule_id: item for item in model.required_concurrency_schedules
    }
    incomplete.update(
        item.schedule_id
        for item in results
        if item.schedule_id in spec_by_id
        and (
            not item.activated
            or (
                spec_by_id[item.schedule_id].fresh_instance_required
                and not item.execution_identity
            )
        )
    )
    fresh_identities = [
        item.execution_identity
        for item in results
        if item.schedule_id in spec_by_id
        and spec_by_id[item.schedule_id].fresh_instance_required
        and item.execution_identity
    ]
    if len(set(fresh_identities)) != len(fresh_identities):
        incomplete.update(
            item.schedule_id
            for item in results
            if item.schedule_id in spec_by_id
            and spec_by_id[item.schedule_id].fresh_instance_required
        )
    if not incomplete:
        return ()
    return (
        finding(
            "CONCURRENCY-INCOMPLETE",
            f"Concurrency schedules are incomplete: {tuple(sorted(incomplete))}.",
            requirement="P2D-07",
            suffix="concurrency-results",
        ),
    )


def _validate_mutations(
    specs: Sequence[MutationSpec],
    results: Sequence[MutationResult],
) -> tuple[Finding, ...]:
    result_by_id = {item.mutant_id: item for item in results}
    survived: list[str] = []
    for spec in specs:
        result = result_by_id.get(spec.mutant_id)
        if result is None or not result.activated or result.status != "killed":
            survived.append(spec.mutant_id)
            continue
        if (
            spec.expected_detection_mode == "finding"
            and spec.expected_finding_code not in result.observed_finding_codes
        ):
            survived.append(spec.mutant_id)
    if not survived:
        return ()
    return (
        finding(
            "MUTATION-SURVIVED",
            f"Required mutants lack attributable kills: {tuple(sorted(survived))}.",
            requirement="P2D-08",
            suffix="mutation-results",
        ),
    )


def _validate_invariants(
    model: DomainModel,
    results: Sequence[InvariantResult],
) -> tuple[Finding, ...]:
    result_by_id = {item.invariant_id: item for item in results}
    incomplete = tuple(
        sorted(
            item.invariant_id
            for item in model.invariants
            if item.required
            and (
                item.invariant_id not in result_by_id
                or result_by_id[item.invariant_id].status != "passed"
            )
        )
    )
    if not incomplete:
        return ()
    return (
        finding(
            "INVARIANT-INCOMPLETE",
            f"Required invariants are incomplete: {incomplete}.",
            requirement="P2D-02",
            suffix="invariant-results",
        ),
    )


def evaluate_qualification(
    model: DomainModel,
    manifest: QualificationRunManifest,
    evidence: EvidenceBundle,
) -> QualificationReport:
    model_findings = validate_domain_model(model)
    manifest_findings = validate_run_manifest(model, manifest)
    exploration = explore_domain(model)
    expected_adapter_sha256 = dict(manifest.component_sha256).get("adapter")
    observation_findings = tuple(
        item
        for envelope, _ in evidence.observations
        for item in validate_observation_envelope(
            model,
            envelope,
            expected_adapter_sha256=expected_adapter_sha256,
        )
    )
    collision_findings = detect_projection_collisions(
        model,
        evidence.observations,
    )
    replay_findings = validate_production_coverage(
        model,
        evidence.replay_results,
    )
    obligation_findings = _validate_obligations(
        model,
        evidence.obligation_results,
    )
    history_findings = reconcile_historical_inventory(
        model.historical_inventory,
        evidence.discovered_history,
    )
    effect_findings = validate_effect_attempts(
        model.effect_surface,
        evidence.effect_attempts,
    )
    static_effect_findings = validate_static_effect_surface(
        model.effect_surface,
        evidence.static_effect_calls,
        evidence.static_effect_callsites,
    )
    effect_class_findings = validate_effect_class_results(
        model.effect_surface,
        evidence.effect_class_results,
    )
    fault_findings = _validate_faults(model, evidence.fault_results)
    concurrency_findings = _validate_concurrency(
        model,
        evidence.concurrency_results,
    )
    mutation_findings = _validate_mutations(
        evidence.mutation_specs,
        evidence.mutation_results,
    )
    invariant_findings = _validate_invariants(
        model,
        evidence.invariant_results,
    )
    all_findings = (
        *model_findings,
        *manifest_findings,
        *exploration.findings,
        *observation_findings,
        *collision_findings,
        *replay_findings,
        *obligation_findings,
        *history_findings,
        *effect_findings,
        *static_effect_findings,
        *effect_class_findings,
        *fault_findings,
        *concurrency_findings,
        *mutation_findings,
        *invariant_findings,
        *evidence.additional_findings,
    )
    unique = {item.finding_id: item for item in all_findings}
    findings = tuple(unique[key] for key in sorted(unique))
    invalid = bool(model_findings or manifest_findings)
    verdict = "invalid" if invalid else ("fail" if findings else "pass")
    complete = verdict != "invalid" and not any(
        item.code
        in {
            "COVERAGE-INCOMPLETE",
            "EFFECT-SURFACE-INCOMPLETE",
            "FAULT-INCOMPLETE",
            "FAULT-MATRIX-INCOMPLETE",
            "CONCURRENCY-INCOMPLETE",
            "CONCURRENCY-MATRIX-INCOMPLETE",
            "MUTATION-SURVIVED",
        }
        for item in findings
    )
    return QualificationReport(
        schema_version="dashboardQualificationReport.v2",
        run_id=manifest.run_id,
        run_manifest_sha256=canonical_sha256(manifest),
        verdict=verdict,
        complete=complete,
        phase1_prerequisite_sha256=manifest.phase1_prerequisite_sha256,
        run_manifest_component_sha256=manifest.component_sha256,
        findings=findings,
        obligation_results=evidence.obligation_results,
        replay_results=evidence.replay_results,
        effect_class_results=evidence.effect_class_results,
        fault_results=evidence.fault_results,
        concurrency_results=evidence.concurrency_results,
        mutation_results=evidence.mutation_results,
        counterexamples=exploration.counterexamples,
        invariant_results=evidence.invariant_results,
        unresolved_state_ids=tuple(
            sorted(
                {
                    state_id
                    for item in exploration.counterexamples
                    for state_id in item.state_ids[-1:]
                }
            )
        ),
        coverage_inventory=tuple(
            sorted(
                (item.obligation_id, item.status)
                for item in evidence.obligation_results
            )
        ),
        telemetry=(
            ("reachable_states", len(exploration.reachable_state_ids)),
            ("obligations", len(model.obligations)),
            ("replays", len(evidence.replay_results)),
            ("effect_attempts", len(evidence.effect_attempts)),
        ),
    )


__all__ = [
    "EvidenceBundle",
    "evaluate_qualification",
    "validate_domain_model",
    "validate_run_manifest",
]
