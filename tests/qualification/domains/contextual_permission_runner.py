from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from tests.qualification.contracts import (
    ConcurrencyConflictSpec,
    ConcurrencyScheduleResult,
    ConcurrencyScheduleSpec,
    EffectClassAuditSpec,
    EffectSurfaceManifest,
    FaultCoverageCell,
    FaultResult,
    FaultSpec,
    Finding,
    InvariantResult,
    InvariantSpec,
    MutationResult,
    MutationSpec,
    ObservationEnvelope,
    ObservationValue,
    ObligationResult,
    ObligationSpec,
    ProductionReplayResult,
    QualificationReport,
    QualificationRunManifest,
    canonical_sha256,
    file_sha256,
    finding,
)
from tests.qualification.coverage import (
    generate_exhaustive_cases,
    generate_pairwise_cases,
    missing_mcdc_conditions,
    reconcile_historical_inventory,
    validate_observation_envelope,
    validate_production_coverage,
)
from tests.qualification.domains.contextual_permission_adapter import (
    ProductionExecution,
    run_changed_upstream_identity_schedule,
    run_production_test,
    run_recovery_race_schedule,
    run_rebuild_concurrency_schedule,
    run_serialized_rebuild_write_schedule,
    run_store_fault_matrix,
    run_writer_fault_matrix,
)
from tests.qualification.domains.contextual_permission_history import (
    discover_historical_capabilities,
    load_declared_historical_inventory,
)
from tests.qualification.domains.contextual_permission_model import (
    build_contextual_permission_model,
)
from tests.qualification.domains.contextual_permission_oracle import (
    UnknownContextualPermissionObservation,
    observe_isolated_project,
    project_contextual_permission_state,
)
from tests.qualification.effects import (
    discover_python_effect_callsites,
    discover_python_sensitive_imports,
    run_absent_effect_canaries,
    validate_effect_attempts,
    validate_effect_class_results,
    validate_static_effect_surface,
)
from tests.qualification.engine import (
    EvidenceBundle,
    evaluate_qualification,
    validate_domain_model,
    validate_run_manifest,
)
from tests.qualification.explorer import explore_domain
from tests.qualification.reporting import (
    FinalizedOutputs,
    exit_code_for,
    finalize_report,
)


PHASE1_PREREQUISITE_SHA256 = (
    "d9ffea5e169c874522bfe2da71244d10907b88b12301766450f661d0c7af84ed"
)

_FIXTURE_ROOT_REF = "tests/qualification/fixtures/contextual_permission"
_CATALOG_REF = f"{_FIXTURE_ROOT_REF}/supported_state_catalog.json"
_REPLAY_REF = f"{_FIXTURE_ROOT_REF}/supported_state_replay_manifest.json"
_HISTORY_REF = f"{_FIXTURE_ROOT_REF}/historical_capability_inventory.json"
_PRODUCTION_REFS = (
    "scout_contextual_permission_workbench.py",
    "scout_contextual_permission_workbench_api.py",
)
_DECISION_AXIS_VALUES = {
    "capability": ("current", "historical", "unknown", "quarantined"),
    "inputs": ("missing", "conflicting", "complete", "invalid"),
    "projection": ("absent", "stale", "fresh", "write_in_doubt", "invalid"),
    "review": ("none", "stale", "current", "invalid"),
}
_DECISION_CRITICAL_COMBINATIONS = (
    {
        "capability": "current",
        "inputs": "complete",
        "projection": "stale",
        "review": "current",
    },
    {
        "capability": "historical",
        "inputs": "missing",
        "projection": "stale",
        "review": "current",
    },
    {
        "capability": "unknown",
        "inputs": "invalid",
        "projection": "absent",
        "review": "none",
    },
    {
        "capability": "quarantined",
        "inputs": "missing",
        "projection": "absent",
        "review": "none",
    },
)


@dataclass(frozen=True)
class QualificationRunOutcome:
    manifest: QualificationRunManifest
    report: QualificationReport
    finalized: FinalizedOutputs
    exit_code: int


def _combined_file_identity(root: Path, refs: tuple[str, ...]) -> str:
    return canonical_sha256(
        tuple((ref, file_sha256(root / ref)) for ref in sorted(refs))
    )


def _effect_surface(root: Path) -> EffectSurfaceManifest:
    callsites = tuple(
        sorted(
            (
                callsite
                for ref in _PRODUCTION_REFS
                for callsite in discover_python_effect_callsites(
                    root / ref,
                    source_ref=ref,
                )
            ),
            key=lambda item: item.callsite_id,
        )
    )
    signatures = {
        *(item.signature for item in callsites),
        *(
            signature
            for ref in _PRODUCTION_REFS
            for signature in discover_python_sensitive_imports(root / ref)
        ),
    }
    operations = (
        "fs.read",
        "fs.mkdir",
        "fs.open",
        "fs.temp_create",
        "fs.write",
        "fs.flush",
        "fs.fsync",
        "fs.link",
        "fs.replace",
        "fs.delete",
        "fs.lock",
        "store.write",
        "ipc.local_socket",
    )
    class_audits = (
        EffectClassAuditSpec(
            "external_store_database",
            "absent",
            (
                "import:boto3",
                "import:psycopg",
                "import:redis",
                "import:sqlite3",
                "import:sqlalchemy",
                "boto3.",
                "psycopg.",
                "redis.",
                "sqlite3.",
                "sqlalchemy.",
            ),
            "canary.absent.external-store-database",
            "database.connect",
            "Permission uses only the declared isolated filesystem-backed store.",
        ),
        EffectClassAuditSpec(
            "http_client",
            "absent",
            (
                "import:aiohttp",
                "import:httpx",
                "import:requests",
                "import:urllib.request",
                "aiohttp.",
                "httpx.",
                "requests.",
                "urllib.request.",
            ),
            "canary.absent.http-client",
            "http.request",
            "No Permission qualification path may access an HTTP client.",
        ),
        EffectClassAuditSpec(
            "network_socket",
            "absent",
            ("import:socket", "socket."),
            "canary.absent.network-socket",
            "network.socket",
            "AF_UNIX TestClient IPC is separately classified as harness-only.",
        ),
        EffectClassAuditSpec(
            "subprocess",
            "absent",
            ("import:subprocess", "subprocess."),
            "canary.absent.subprocess",
            "subprocess.run",
            "Permission qualification executes in-process without child commands.",
        ),
        EffectClassAuditSpec(
            "runtime_safety_adapter",
            "absent",
            ("import:scout_runtime", "import:scout_safety", "runtime_adapter.", "safety_adapter."),
            "canary.absent.runtime-safety-adapter",
            "runtime_safety.invoke",
            "Candidate Permission evidence cannot mutate runtime or safety truth.",
        ),
        EffectClassAuditSpec(
            "outbound_sender",
            "absent",
            ("import:outbound", "import:telegram", "outbound.", "sender.send"),
            "canary.absent.outbound-sender",
            "outbound.send",
            "No outbound sender is authorized in this internal qualification.",
        ),
        EffectClassAuditSpec(
            "hardware_interface",
            "absent",
            ("import:hardware", "import:gpio", "hardware.", "gpio."),
            "canary.absent.hardware-interface",
            "hardware.control",
            "No hardware interface is authorized in this internal qualification.",
        ),
    )
    phase_policy = {
        "fs.read": {"before", "inside", "after"},
        "fs.mkdir": {"before", "after"},
        "fs.open": {"before"},
        "fs.temp_create": {"before"},
        "fs.write": {"before", "inside", "after"},
        "fs.flush": {"before", "inside", "after"},
        "fs.fsync": {"before", "inside", "after"},
        "fs.link": {"before", "after"},
        "fs.replace": {"before", "after"},
        "fs.delete": {"before", "after"},
        "fs.lock": {"before", "after"},
        "store.write": {"before", "inside", "after"},
        "ipc.local_socket": set(),
    }
    fault_coverage = tuple(
        FaultCoverageCell(
            effect_operation=operation,
            injection_phase=phase,  # type: ignore[arg-type]
            applicability=(
                "required" if phase in phase_policy[operation] else "not_applicable"
            ),
            fault_id=(
                f"fault.matrix.{operation.replace('.', '-')}.{phase}"
                if phase in phase_policy[operation]
                else None
            ),
            rationale=(
                ""
                if phase in phase_policy[operation]
                else (
                    "Harness-only local IPC is not a production Permission effect."
                    if operation == "ipc.local_socket"
                    else "The primitive is atomic at this boundary; partial behavior is covered by its surrounding write primitive."
                )
            ),
        )
        for operation in operations
        for phase in ("before", "inside", "after")
    )
    return EffectSurfaceManifest(
        source_sha256=_combined_file_identity(root, _PRODUCTION_REFS),
        operations=operations,
        allowed_read_roots=("workspace", "fixture", "production_source"),
        allowed_write_roots=("workspace",),
        absent_effect_classes=tuple(item.effect_class for item in class_audits),
        static_call_signatures=tuple(sorted(signatures)),
        callsites=callsites,
        class_audits=class_audits,
        fault_coverage=fault_coverage,
    )


def _fault_specs(surface: EffectSurfaceManifest) -> tuple[FaultSpec, ...]:
    expected_by_cell = {
        ("fs.link", "after"): ("post_state",),
        ("fs.replace", "after"): ("post_state",),
        ("fs.delete", "before"): ("post_state",),
        ("fs.delete", "after"): ("post_state",),
        ("store.write", "inside"): ("post_state",),
        ("store.write", "after"): ("write_in_doubt",),
    }
    return tuple(
        FaultSpec(
            fault_id=cell.fault_id or "",
            effect_operation=cell.effect_operation,
            injection_point=f"{cell.injection_phase}-{cell.effect_operation}",
            expected_terminal_kinds=expected_by_cell.get(
                (cell.effect_operation, cell.injection_phase),
                ("pre_state",),
            ),
            injection_phase=cell.injection_phase,
        )
        for cell in surface.fault_coverage
        if cell.applicability == "required"
    )


_SHARED_WRITE_YIELDS = (
    "admission",
    "journal-creation",
    "planned-eta-write",
    "rules-write",
    "seed-write",
    "stale-marker-write",
    "project-pointer-activation",
    "receipt-write",
    "journal-cleanup",
)


def _concurrency_conflicts() -> tuple[ConcurrencyConflictSpec, ...]:
    return (
        ConcurrencyConflictSpec(
            "pair.same-snapshot-same-key",
            "projection.rebuild.same-key.left",
            "projection.rebuild.same-key.right",
            _SHARED_WRITE_YIELDS,
        ),
        ConcurrencyConflictSpec(
            "pair.same-snapshot-different-key",
            "projection.rebuild.left",
            "projection.rebuild.right",
            _SHARED_WRITE_YIELDS,
        ),
        ConcurrencyConflictSpec(
            "pair.changed-upstream-identity",
            "projection.rebuild.old",
            "baseline.activate.new",
            _SHARED_WRITE_YIELDS,
        ),
        ConcurrencyConflictSpec(
            "pair.recovery-versus-new-command",
            "projection.recover.exact-key",
            "projection.rebuild.new-command",
            ("recovery",),
        ),
    )


def _concurrency_schedules(
    conflicts: tuple[ConcurrencyConflictSpec, ...],
) -> tuple[ConcurrencyScheduleSpec, ...]:
    return tuple(
        ConcurrencyScheduleSpec(
            schedule_id=(
                f"schedule.{pair.conflict_pair_id.removeprefix('pair.')}."
                f"{yield_point}"
            ),
            left_command_id=pair.left_command_id,
            right_command_id=pair.right_command_id,
            yield_point=yield_point,
            conflict_pair_id=pair.conflict_pair_id,
        )
        for pair in conflicts
        for yield_point in pair.applicable_yield_points
    )


def build_default_contextual_permission_model(repository_root: Path):
    root = Path(repository_root)
    effect_surface = _effect_surface(root)
    concurrency_conflicts = _concurrency_conflicts()
    history = load_declared_historical_inventory(
        root,
        manifest_path=root / _HISTORY_REF,
    )
    model = build_contextual_permission_model(
        catalog_path=root / _CATALOG_REF,
        replay_manifest_path=root / _REPLAY_REF,
        historical_inventory=history,
        effect_surface=effect_surface,
    )
    extra_obligations = (
        ObligationSpec("decision:exhaustive", "decision_coverage", "small-gates"),
        ObligationSpec("decision:pairwise", "decision_coverage", "state-axes"),
        ObligationSpec("decision:mcdc", "decision_coverage", "rebuild-admission"),
        ObligationSpec("effect:static-surface", "effect_surface", "production"),
        ObligationSpec("phase1:semantic-regression", "regression", "phase1-rev3"),
    )
    return dataclasses.replace(
        model,
        obligations=(*model.obligations, *extra_obligations),
        required_faults=_fault_specs(effect_surface),
        required_concurrency_schedules=_concurrency_schedules(
            concurrency_conflicts
        ),
        concurrency_conflicts=concurrency_conflicts,
        invariants=(
            InvariantSpec(
                "invariant.supported-start-terminal",
                "P2D-04",
                "Every supported start reaches an accepted terminal.",
            ),
            InvariantSpec(
                "invariant.historical-reconciliation",
                "P2D-06",
                "Every discovered capability has a declared disposition.",
            ),
            InvariantSpec(
                "invariant.read-command-agreement",
                "P2D-04",
                "Production commands and independent terminal observations agree.",
            ),
            InvariantSpec(
                "invariant.effect-confinement",
                "P2D-07",
                "All attempted effects remain declared and confined.",
            ),
            InvariantSpec(
                "invariant.fault-recovery",
                "P2D-07",
                "Required interrupted transitions recover to a typed full state.",
            ),
            InvariantSpec(
                "invariant.concurrency-conflicts",
                "P2D-07",
                "Required conflict schedules produce deterministic success or rejection.",
            ),
            InvariantSpec(
                "invariant.phase1-semantic-parity",
                "P2D-10",
                "Retained Phase 1 rev3 semantic outcomes remain exact.",
            ),
        ),
    )


def _run_manifest(root: Path, model) -> QualificationRunManifest:
    engine_refs = (
        "tests/qualification/contracts.py",
        "tests/qualification/coverage.py",
        "tests/qualification/effects.py",
        "tests/qualification/engine.py",
        "tests/qualification/explorer.py",
        "tests/qualification/reporting.py",
    )
    fixture_refs = (
        _CATALOG_REF,
        _REPLAY_REF,
        _HISTORY_REF,
        f"{_FIXTURE_ROOT_REF}/transition_effect_allowlist.json",
        f"{_FIXTURE_ROOT_REF}/legacy_sparse_livelock_trace.json",
    )
    component_sha256 = (
        ("engine", _combined_file_identity(root, engine_refs)),
        ("model", canonical_sha256(model)),
        (
            "oracle",
            file_sha256(
                root
                / "tests/qualification/domains/contextual_permission_oracle.py"
            ),
        ),
        (
            "adapter",
            file_sha256(
                root
                / "tests/qualification/domains/contextual_permission_adapter.py"
            ),
        ),
        ("production", _combined_file_identity(root, _PRODUCTION_REFS)),
        ("fixtures", _combined_file_identity(root, fixture_refs)),
        ("history", canonical_sha256(model.historical_inventory)),
        ("effects", canonical_sha256(model.effect_surface)),
        ("bounds", canonical_sha256({"graph": "complete", "production": 32})),
        (
            "decisions",
            canonical_sha256(
                {
                    "exhaustive": True,
                    "pairwise_axes": _DECISION_AXIS_VALUES,
                    "critical_combinations": _DECISION_CRITICAL_COMBINATIONS,
                    "mcdc": True,
                }
            ),
        ),
        ("faults", canonical_sha256(model.required_faults)),
        (
            "concurrency",
            canonical_sha256(model.required_concurrency_schedules),
        ),
        ("mutants", canonical_sha256(_mutation_specs())),
        (
            "configuration",
            canonical_sha256(
                {"domain": "contextual_permission", "phase": 2, "seed": 41}
            ),
        ),
    )
    return QualificationRunManifest(
        run_id=f"contextual-permission.phase2.{canonical_sha256(model)[:12]}",
        phase1_prerequisite_sha256=PHASE1_PREREQUISITE_SHA256,
        component_sha256=component_sha256,
        deterministic_clock="2026-08-04T00:00:00Z",
        deterministic_seed=41,
    )


def _decision_results() -> tuple[tuple[ObligationResult, ...], tuple[Finding, ...]]:
    findings: list[Finding] = []
    exhaustive = generate_exhaustive_cases(
        {
            "capability_current": (False, True),
            "review_binding_current": (False, True),
            "inputs_complete": (False, True),
            "write_in_doubt_absent": (False, True),
        }
    )
    if len(exhaustive) != 16:
        findings.append(
            finding(
                "DECISION-COVERAGE-INCOMPLETE",
                "The exhaustive rebuild-admission table is incomplete.",
                requirement="P2D-05",
                suffix="exhaustive",
            )
        )
    pairwise = (
        *generate_pairwise_cases(_DECISION_AXIS_VALUES),
        *_DECISION_CRITICAL_COMBINATIONS,
    )
    for left_index, left in enumerate(sorted(_DECISION_AXIS_VALUES)):
        for right in sorted(_DECISION_AXIS_VALUES)[left_index + 1 :]:
            expected = {
                (left_value, right_value)
                for left_value in _DECISION_AXIS_VALUES[left]
                for right_value in _DECISION_AXIS_VALUES[right]
            }
            observed = {(case[left], case[right]) for case in pairwise}
            if not expected <= observed:
                findings.append(
                    finding(
                        "DECISION-COVERAGE-INCOMPLETE",
                        f"Pairwise coverage is incomplete for {left}/{right}.",
                        requirement="P2D-05",
                        suffix=f"pairwise.{left}.{right}",
                    )
                )
    mcdc_rows = tuple(
        (
            values,
            all(values.values()),
        )
        for values in exhaustive
    )
    missing_mcdc = missing_mcdc_conditions(
        (
            "capability_current",
            "review_binding_current",
            "inputs_complete",
            "write_in_doubt_absent",
        ),
        mcdc_rows,
    )
    if missing_mcdc:
        findings.append(
            finding(
                "DECISION-COVERAGE-INCOMPLETE",
                f"MC/DC witnesses are missing: {missing_mcdc}.",
                requirement="P2D-05",
                suffix="mcdc",
            )
        )
    by_obligation = {
        "decision:exhaustive": not any("exhaustive" in item.finding_id for item in findings),
        "decision:pairwise": not any("pairwise" in item.finding_id for item in findings),
        "decision:mcdc": not any("mcdc" in item.finding_id for item in findings),
    }
    return (
        tuple(
            ObligationResult(
                obligation_id,
                "passed" if passed else "failed",
                f"decision-evidence:{obligation_id}",
            )
            for obligation_id, passed in sorted(by_obligation.items())
        ),
        tuple(findings),
    )


def _mutation_specs() -> tuple[MutationSpec, ...]:
    return (
        MutationSpec(
            "mutant.schema-drift-without-migration",
            "historical_inventory.legacy_sparse.v1.disposition",
            "migration disposition changed to direct support",
            "compatibility:legacy-to-ref-gpx",
            "HISTORICAL-INVENTORY-MISMATCH",
        ),
        MutationSpec(
            "mutant.removed-recovery-edge",
            "model.transitions.retry-interrupted-rebuild",
            "required recovery edge removed",
            "transition:retry-interrupted-rebuild",
            "FLOW-BLOCKED",
        ),
        MutationSpec(
            "mutant.required-transition-removed",
            "model.transitions.save-proposal-candidate",
            "required non-recovery transition removed",
            "transition:save-proposal-candidate",
            "FLOW-BLOCKED",
        ),
        MutationSpec(
            "mutant.predicate-divergence",
            "phase1.admission.command_admitted",
            "eligible read disagrees with command",
            "transition:rebuild-stale-projection",
            "PREDICATE-DIVERGENCE",
        ),
        MutationSpec(
            "mutant.volatile-only-progress",
            "model.states.projection-fresh-policy-pending.progress_signature",
            "semantic progress replaced by source signature",
            "transition:rebuild-stale-projection",
            "RECOVERY-NO-PROGRESS",
        ),
        MutationSpec(
            "mutant.partial-write-marked-fresh",
            "observation.projection-write-in-doubt.projection",
            "write-in-doubt projection changed to fresh",
            "transition:retry-interrupted-rebuild",
            "UNKNOWN-SEMANTIC-STATE",
            expected_detection_mode="exception",
        ),
        MutationSpec(
            "mutant.stale-review-current",
            "phase1.state.baseline_review_binding",
            "stale dependency mislabeled ready",
            "terminal:ready",
            "DEPENDENCY-SPLIT-BRAIN",
        ),
        MutationSpec(
            "mutant.forbidden-outbound",
            "phase1.effect.forbidden_effects",
            "outbound transport attempted",
            "effect:static-surface",
            "FORBIDDEN-EFFECT",
        ),
        MutationSpec(
            "mutant.supported-start-removed",
            "model.supported_start_state_ids",
            "projection-write-in-doubt start removed",
            "start:projection-write-in-doubt",
            "RUN-MANIFEST-MISMATCH",
        ),
        MutationSpec(
            "mutant.nonterminal-replay-labeled-pass",
            "production_replay.observed_terminal_id",
            "missing terminal mislabeled pass",
            "terminal:ready",
            "COVERAGE-INCOMPLETE",
        ),
        MutationSpec(
            "mutant.omitted-semantic-observation-field",
            "observation.fields.baseline_capability",
            "required semantic observation field omitted",
            "start:no-baseline",
            "OBSERVATION-FIELD-MISSING",
        ),
    )


def _phase1_regression_and_mutations(
    root: Path,
    execution_root: Path,
    model,
    manifest: QualificationRunManifest,
) -> tuple[ObligationResult, tuple[MutationResult, ...], tuple, tuple[Finding, ...]]:
    regression_runners = (
        "test_historical_trace_reports_shortest_closed_livelock",
        "test_dual_migration_witness_reaches_ready_without_equating_safe_blocker",
        "test_recovery_rank_mutation_canary_fails",
        "test_predicate_divergence_mutation_canary_fails",
        "test_review_binding_mutation_canary_fails",
        "test_forbidden_effect_mutation_canary_fails",
    )
    executions: dict[str, ProductionExecution] = {}
    attempts = []
    findings: list[Finding] = []
    for index, runner_id in enumerate(regression_runners):
        execution = run_production_test(
            runner_id,
            execution_root=execution_root / f"phase1-{index:02d}",
            repository_root=root,
        )
        executions[runner_id] = execution
        attempts.extend(execution.effect_attempts)
        if execution.status != "passed":
            findings.append(
                finding(
                    "PHASE1-SEMANTIC-REGRESSION",
                    f"Retained Phase 1 semantic case failed: {runner_id}.",
                    requirement="P2D-10",
                    evidence=(execution.detail,),
                    suffix=runner_id,
                )
            )
    results: list[MutationResult] = []

    def record(
        mutant_id: str,
        observed_codes: tuple[str, ...],
        *,
        detail: str,
        activated: bool = True,
    ) -> None:
        spec = next(item for item in _mutation_specs() if item.mutant_id == mutant_id)
        killed = (
            activated
            and spec.expected_finding_code in observed_codes
        )
        results.append(
            MutationResult(
                mutant_id,
                activated,
                "killed" if killed else "survived",
                observed_codes,
                detail,
            )
        )

    legacy_record = next(
        item
        for item in model.historical_inventory.records
        if item.capability_id == "legacy_sparse.v1"
    )
    discovered = tuple(
        dataclasses.replace(item, disposition="direct_support", migration_or_recovery_id=None)
        if item == legacy_record
        else item
        for item in model.historical_inventory.records
    )
    record(
        "mutant.schema-drift-without-migration",
        tuple(
            item.code
            for item in reconcile_historical_inventory(
                model.historical_inventory,
                discovered,
            )
        ),
        detail="isolated historical disposition mutation",
    )

    removed_edge_model = dataclasses.replace(
        model,
        transitions=tuple(
            item
            for item in model.transitions
            if item.transition_id != "retry-interrupted-rebuild"
        ),
    )
    record(
        "mutant.removed-recovery-edge",
        tuple(item.code for item in explore_domain(removed_edge_model).findings),
        detail="isolated declarative edge removal",
        activated=len(removed_edge_model.transitions) + 1 == len(model.transitions),
    )

    required_transition = next(
        item
        for item in model.transitions
        if item.transition_id == "save-proposal-candidate"
    )
    removed_required_transition_model = dataclasses.replace(
        model,
        transitions=tuple(
            item
            for item in model.transitions
            if item.transition_id != required_transition.transition_id
        ),
    )
    record(
        "mutant.required-transition-removed",
        tuple(
            item.code
            for item in explore_domain(
                removed_required_transition_model
            ).findings
        ),
        detail=(
            "isolated required non-recovery transition removal: "
            "save-proposal-candidate"
        ),
        activated=(
            required_transition.required
            and not required_transition.advertised_recovery
            and len(removed_required_transition_model.transitions) + 1
            == len(model.transitions)
        ),
    )

    phase1_mapping = (
        (
            "mutant.predicate-divergence",
            "test_predicate_divergence_mutation_canary_fails",
            "PREDICATE-DIVERGENCE",
        ),
        (
            "mutant.stale-review-current",
            "test_review_binding_mutation_canary_fails",
            "DEPENDENCY-SPLIT-BRAIN",
        ),
        (
            "mutant.forbidden-outbound",
            "test_forbidden_effect_mutation_canary_fails",
            "FORBIDDEN-EFFECT",
        ),
    )
    for mutant_id, runner_id, expected_code in phase1_mapping:
        passed = executions[runner_id].status == "passed"
        record(
            mutant_id,
            (expected_code,) if passed else (),
            detail=f"isolated runner: {runner_id}",
            activated=passed,
        )

    recovery = next(
        item
        for item in model.transitions
        if item.transition_id == "rebuild-stale-projection"
    )
    source = next(
        item for item in model.states if item.state_id == recovery.source_state_id
    )
    mutated_states = tuple(
        dataclasses.replace(item, progress_signature=source.progress_signature)
        if item.state_id == recovery.target_state_id
        else item
        for item in model.states
    )
    volatile_model = dataclasses.replace(model, states=mutated_states)
    record(
        "mutant.volatile-only-progress",
        tuple(item.code for item in validate_domain_model(volatile_model)),
        detail="isolated progress-signature mutation",
    )

    write_in_doubt = next(
        item for item in model.states if item.state_id == "projection-write-in-doubt"
    )
    partial_fields = tuple(
        ObservationValue(
            path=f"/{name}",
            provenance="raw_persisted_fact",
            canonical_value_json=next(
                value
                for axis, value in write_in_doubt.semantic_axes
                if axis == name
            ),
        )
        for name in (
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
    )
    partial_fields = tuple(
        dataclasses.replace(
            item,
            canonical_value_json='"fresh"',
        )
        if item.path == "/projection"
        else item
        for item in partial_fields
    )
    partial_envelope = ObservationEnvelope(
        "mutant.partial-write",
        "mutation",
        "a" * 64,
        canonical_sha256(model.observation_fields),
        dict(manifest.component_sha256)["adapter"],
        partial_fields,
    )
    partial_codes: tuple[str, ...] = ()
    try:
        project_contextual_permission_state(partial_envelope, model=model)
    except UnknownContextualPermissionObservation:
        partial_codes = ("UNKNOWN-SEMANTIC-STATE",)
    record(
        "mutant.partial-write-marked-fresh",
        partial_codes,
        detail="isolated write-in-doubt observation mutation",
    )

    removed_start_model = dataclasses.replace(
        model,
        supported_start_state_ids=tuple(
            item
            for item in model.supported_start_state_ids
            if item != "projection-write-in-doubt"
        ),
    )
    record(
        "mutant.supported-start-removed",
        tuple(item.code for item in validate_run_manifest(removed_start_model, manifest)),
        detail="isolated run-manifest/model identity mutation",
    )

    replay = next(
        item for item in model.production_replays if item.witness_kind == "production"
    )
    bad_replay = ProductionReplayResult(
        replay.replay_id,
        "passed",
        None,
        replay.covers_obligation_ids,
        "mutant omitted accepted terminal",
    )
    replay_codes = tuple(
        item.code
        for item in validate_production_coverage(model, (bad_replay,))
    )
    record(
        "mutant.nonterminal-replay-labeled-pass",
        replay_codes,
        detail="isolated replay-terminal mutation",
    )

    no_baseline = next(
        item for item in model.states if item.state_id == "no-baseline"
    )
    omitted_semantic_envelope = ObservationEnvelope(
        "mutant.omitted-semantic-observation-field",
        "mutation",
        "b" * 64,
        canonical_sha256(model.observation_fields),
        dict(manifest.component_sha256)["adapter"],
        tuple(
            ObservationValue(
                path=f"/{axis}",
                provenance="raw_persisted_fact",
                canonical_value_json=value,
            )
            for axis, value in no_baseline.semantic_axes
            if axis != "baseline_capability"
        ),
    )
    omitted_semantic_codes = tuple(
        item.code
        for item in validate_observation_envelope(
            model,
            omitted_semantic_envelope,
            expected_adapter_sha256=dict(manifest.component_sha256)["adapter"],
        )
    )
    record(
        "mutant.omitted-semantic-observation-field",
        omitted_semantic_codes,
        detail="isolated required semantic observation-field omission",
    )
    mutation_results = tuple(results)
    return (
        ObligationResult(
            "phase1:semantic-regression",
            "passed" if not findings else "failed",
            "phase1-rev3-semantic-replay",
        ),
        mutation_results,
        tuple(attempts),
        tuple(findings),
    )


def run_contextual_permission_qualification(
    *,
    repository_root: Path,
    execution_root: Path,
    result_root: Path,
) -> QualificationRunOutcome:
    root = Path(repository_root).resolve()
    execution = Path(execution_root).resolve()
    if execution.exists() and any(execution.iterdir()):
        raise ValueError("qualification execution root must be empty")
    execution.mkdir(parents=True, exist_ok=True)
    model = build_default_contextual_permission_model(root)
    manifest = _run_manifest(root, model)
    observations = []
    attempts = []
    replay_results: list[ProductionReplayResult] = []
    executions_by_runner: dict[str, ProductionExecution] = {}
    additional_findings: list[Finding] = []
    adapter_sha256 = dict(manifest.component_sha256)["adapter"]
    for index, replay in enumerate(model.production_replays):
        if replay.witness_kind != "production":
            replay_results.append(
                ProductionReplayResult(
                    replay.replay_id,
                    "infeasible",
                    replay.expected_terminal_id,
                    replay.covers_obligation_ids,
                    "Explicit quarantine witness; no mutating production command exists.",
                )
            )
            continue
        production = run_production_test(
            replay.runner_id,
            execution_root=execution / f"replay-{index:02d}",
            repository_root=root,
        )
        executions_by_runner.setdefault(replay.runner_id, production)
        attempts.extend(production.effect_attempts)
        status = production.status
        observed_terminal_id = None
        detail = production.detail
        if status == "passed" and replay.expected_terminal_id is not None:
            try:
                observed = observe_isolated_project(
                    production.project_root,
                    source_id=replay.replay_id,
                    adapter_sha256=adapter_sha256,
                    model=model,
                )
                observations.append((observed.envelope, observed.state))
                observed_terminal_id = observed.state.terminal_id
                if observed_terminal_id != replay.expected_terminal_id:
                    status = "failed"
                    detail = (
                        f"independent oracle observed {observed.state.state_id} "
                        f"instead of {replay.expected_terminal_id}"
                    )
            except (OSError, ValueError, UnknownContextualPermissionObservation) as error:
                status = "failed"
                detail = f"independent observation failed: {error}"
        replay_results.append(
            ProductionReplayResult(
                replay.replay_id,
                status,  # type: ignore[arg-type]
                observed_terminal_id,
                replay.covers_obligation_ids if status == "passed" else (),
                detail,
            )
        )

    result_by_replay = {item.replay_id: item for item in replay_results}
    obligation_results = [
        ObligationResult(
            obligation.obligation_id,
            (
                "passed"
                if any(
                    result.status in {"passed", "infeasible"}
                    and obligation.obligation_id in result.covered_obligation_ids
                    for result in replay_results
                )
                else "not_run"
            ),
            next(
                (
                    replay_id
                    for replay_id, result in result_by_replay.items()
                    if obligation.obligation_id in result.covered_obligation_ids
                ),
                "",
            ),
        )
        for obligation in model.obligations
        if obligation.kind
        in {
            "supported_start",
            "transition",
            "terminal",
            "compatibility",
            "external_operator",
        }
    ]
    decision_results, decision_findings = _decision_results()
    obligation_results.extend(decision_results)
    additional_findings.extend(decision_findings)
    obligation_results.append(
        ObligationResult(
            "effect:static-surface",
            "passed",
            "static-effect-callsite-inventory",
        )
    )

    static_callsites = tuple(
        sorted(
            (
                callsite
                for ref in _PRODUCTION_REFS
                for callsite in discover_python_effect_callsites(
                    root / ref,
                    source_ref=ref,
                )
            ),
            key=lambda item: item.callsite_id,
        )
    )
    static_calls = tuple(
        sorted(
            {
                *(item.signature for item in static_callsites),
                *(
                    signature
                    for ref in _PRODUCTION_REFS
                    for signature in discover_python_sensitive_imports(root / ref)
                ),
            }
        )
    )
    effect_class_results, canary_attempts = run_absent_effect_canaries(
        model.effect_surface,
        execution_root=execution / "absent-effect-canaries",
        discovered_calls=static_calls,
    )
    attempts.extend(canary_attempts)

    fault_results: list[FaultResult] = []
    writer_faults = run_writer_fault_matrix(
        fault_specs=model.required_faults,
        execution_root=execution / "writer-fault-matrix",
        repository_root=root,
    )
    fault_results.extend(writer_faults.results)
    attempts.extend(writer_faults.effect_attempts)
    store_faults = run_store_fault_matrix(
        fault_specs=model.required_faults,
        execution_root=execution / "store-fault-matrix",
        repository_root=root,
    )
    fault_results.extend(store_faults.results)
    attempts.extend(store_faults.effect_attempts)

    concurrency_results_list: list[ConcurrencyScheduleResult] = []
    for index, schedule in enumerate(model.required_concurrency_schedules):
        schedule_root = execution / f"concurrency-{index:02d}"
        if schedule.yield_point == "admission":
            if schedule.conflict_pair_id == "pair.changed-upstream-identity":
                concurrency = run_changed_upstream_identity_schedule(
                    execution_root=schedule_root,
                    repository_root=root,
                )
            else:
                concurrency = run_rebuild_concurrency_schedule(
                    schedule.schedule_id,
                    execution_root=schedule_root,
                    repository_root=root,
                )
        elif schedule.yield_point == "recovery":
            concurrency = run_recovery_race_schedule(
                execution_root=schedule_root,
                repository_root=root,
            )
        else:
            concurrency = run_serialized_rebuild_write_schedule(
                conflict_pair_id=schedule.conflict_pair_id,
                yield_point=schedule.yield_point,
                execution_root=schedule_root,
                repository_root=root,
            )
        if concurrency.schedule_id != schedule.schedule_id:
            concurrency_results_list.append(
                ConcurrencyScheduleResult(
                    schedule.schedule_id,
                    "failed",
                    "schedule-identity-mismatch",
                    (
                        f"adapter returned {concurrency.schedule_id} for "
                        f"{schedule.schedule_id}"
                    ),
                    activated=False,
                    execution_identity=concurrency.execution_identity,
                )
            )
        else:
            concurrency_results_list.append(
                ConcurrencyScheduleResult(
                    schedule.schedule_id,
                    concurrency.status,  # type: ignore[arg-type]
                    concurrency.observed_result,
                    concurrency.detail,
                    activated=concurrency.activated,
                    execution_identity=concurrency.execution_identity,
                )
            )
        attempts.extend(concurrency.effect_attempts)
    concurrency_results = tuple(concurrency_results_list)
    (
        phase1_result,
        mutation_results,
        phase1_attempts,
        phase1_findings,
    ) = _phase1_regression_and_mutations(
        root,
        execution,
        model,
        manifest,
    )
    obligation_results.append(phase1_result)
    attempts.extend(phase1_attempts)
    additional_findings.extend(phase1_findings)
    invariant_checks = {
        "invariant.supported-start-terminal": not explore_domain(model).findings,
        "invariant.historical-reconciliation": not reconcile_historical_inventory(
            model.historical_inventory,
            discover_historical_capabilities(root),
        ),
        "invariant.read-command-agreement": all(
            item.status in {"passed", "infeasible"}
            for item in replay_results
        ),
        "invariant.effect-confinement": not (
            validate_effect_attempts(model.effect_surface, attempts)
            or validate_static_effect_surface(
                model.effect_surface,
                static_calls,
                static_callsites,
            )
            or validate_effect_class_results(
                model.effect_surface,
                effect_class_results,
            )
        ),
        "invariant.fault-recovery": all(
            item.status == "passed" for item in fault_results
        ),
        "invariant.concurrency-conflicts": all(
            item.status == "passed" for item in concurrency_results
        ),
        "invariant.phase1-semantic-parity": phase1_result.status == "passed",
    }
    invariant_results = tuple(
        InvariantResult(
            invariant_id,
            "passed" if passed else "failed",
            f"invariant-evidence:{invariant_id}",
        )
        for invariant_id, passed in sorted(invariant_checks.items())
    )
    evidence = EvidenceBundle(
        observations=tuple(observations),
        obligation_results=tuple(obligation_results),
        replay_results=tuple(replay_results),
        discovered_history=discover_historical_capabilities(root),
        effect_attempts=tuple(attempts),
        effect_class_results=effect_class_results,
        fault_results=tuple(fault_results),
        concurrency_results=concurrency_results,
        mutation_specs=_mutation_specs(),
        mutation_results=mutation_results,
        static_effect_calls=static_calls,
        static_effect_callsites=static_callsites,
        additional_findings=tuple(additional_findings),
        invariant_results=invariant_results,
    )
    report = evaluate_qualification(model, manifest, evidence)
    finalized = finalize_report(report, Path(result_root))
    return QualificationRunOutcome(
        manifest=manifest,
        report=report,
        finalized=finalized,
        exit_code=exit_code_for(report, finalized=True),
    )


__all__ = [
    "PHASE1_PREREQUISITE_SHA256",
    "QualificationRunOutcome",
    "build_default_contextual_permission_model",
    "run_contextual_permission_qualification",
]
