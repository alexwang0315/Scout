from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from tests.qualification.contracts import canonical_json, canonical_sha256, file_sha256
from tests.qualification.domains.contextual_permission_runner import (
    run_contextual_permission_qualification,
)
from tests.qualification.phase3_catalog import (
    AUTHORITY_BOUNDARIES,
    COMMAND_RESOURCES,
    DEPENDENCY_EDGES,
    DOMAIN_IDS,
    DOMAIN_SPECS,
    PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256,
    PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256,
    PHASE2_MANIFEST_SEMANTIC_SHA256,
    PHASE2_REPORT_CANONICAL_SHA256,
    PHASE2_REPORT_SEMANTIC_SHA256,
    PHASE3_DESIGN_CANONICAL_SHA256,
)
from tests.qualification.phase3_contracts import (
    AuthorityReceipt,
    NotApplicableWitness,
    Phase3AggregateReport,
    Phase3CaseResult,
    Phase3DomainReport,
    Phase3Finding,
)
from tests.qualification.phase3_discovery import (
    SurfaceDiscovery,
    discover_dashboard_surface,
    verify_design_packet,
)
from tests.qualification.phase3_execution import run_conflict_matrix, run_fault_matrix
from tests.qualification.phase3_mutations import run_phase3_mutations
from tests.qualification.phase3_phase2_lineage import (
    exit_code_for_phase2_lineage,
    load_phase2_lineage_contract,
    validate_phase2_lineage,
)
from tests.qualification.phase3_replays import (
    ProductionReplayEvidence,
    fixture_case,
    run_production_replay,
)
from tests.qualification.phase3_reporting import (
    Phase3DomainFinalizedOutputs,
    Phase3FinalizedOutputs,
    exit_code_for_phase3,
    exit_code_for_phase3_domain,
    finalize_phase3_domain_report,
    finalize_phase3_reports,
)
from tests.qualification.phase3_validation import (
    PRIVATE_SENTINEL_SINKS,
    derive_conflict_schedules,
    derive_dependency_race_schedules,
    derive_fault_cells,
    discover_effect_inventory,
    private_sentinel_tokens,
    run_dependency_case,
    scan_private_sentinels,
    validate_authority_receipt,
    validate_conflict_results,
    validate_default_catalog,
    validate_dependency_cases,
    validate_fault_results,
    validate_not_applicable_witness,
)
from tests.qualification.phase3_workspace import (
    WORKSPACE_CAPABILITY_SCHEMA,
    inventory_workspace,
    validate_workspace_snapshot,
)


PHASE2_DESIGN_CANONICAL_SHA256 = (
    "f982b1f85cb324a697e6c74d27e173917553226493d8f652d5c2621b121b73bb"
)
PHASE2_CLOSURE_CANONICAL_SHA256 = (
    "76247f4e723ed6cc79144707ce103400d68f180f9ec16ab283d3d328e987c027"
)
PHASE2_CLOSURE_SERIALIZED_SHA256 = (
    "decf5f20f8e36a88f65e72b5278c323bbf4fc2d1a749d13c93519927e5bf6164"
)
PHASE2_DETERMINISM_ADDENDUM_SERIALIZED_SHA256 = (
    "1325730477dc7d07b2e5db2f931e63ab78399673a0fae8e1fea30b3c19004f93"
)


@dataclass(frozen=True)
class Phase3RunOutcome:
    report: Phase3AggregateReport
    domain_reports: tuple[tuple[str, Phase3DomainReport], ...]
    finalized: Phase3FinalizedOutputs
    exit_code: int


@dataclass(frozen=True)
class Phase3DomainRunOutcome:
    report: Phase3DomainReport
    finalized: Phase3DomainFinalizedOutputs
    exit_code: int


def _finding(
    code: str,
    summary: str,
    *,
    requirement: str,
    evidence: tuple[str, ...] = (),
) -> Phase3Finding:
    suffix = hashlib.sha256(f"{code}\0{summary}".encode()).hexdigest()[:12]
    return Phase3Finding(
        finding_id=f"{code.lower()}.{suffix}",
        code=code,
        severity="blocking",
        summary=summary,
        requirement_refs=(requirement,),
        evidence_refs=evidence,
    )


def _case(
    case_id: str,
    category: str,
    *,
    passed: bool,
    evidence: object,
    activated: bool = True,
    not_applicable: bool = False,
    finding_codes: tuple[str, ...] = (),
) -> Phase3CaseResult:
    return Phase3CaseResult(
        case_id=case_id,
        category=category,
        status=(
            "not_applicable"
            if not_applicable and passed
            else "passed" if passed else "failed"
        ),
        activated=activated,
        evidence_ref=canonical_sha256(evidence),
        finding_codes=finding_codes,
    )


def _canonical_packet_hash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("content_sha256", None)
    return canonical_sha256(payload)


def _verify_prerequisite_files(root: Path) -> tuple[Phase3Finding, ...]:
    findings: list[Phase3Finding] = []
    paths = (
        (
            "phase2-design",
            root / "docs/evals/dashboard-internal-qualification-phase2-design-rev2.json",
            PHASE2_DESIGN_CANONICAL_SHA256,
        ),
        (
            "phase2-closure",
            root / "docs/evals/dashboard-internal-qualification-phase2-closure-rev2.json",
            PHASE2_CLOSURE_CANONICAL_SHA256,
        ),
        (
            "phase2-determinism-addendum",
            root
            / "docs/evals/dashboard-internal-qualification-phase2-determinism-addendum-rev2.json",
            PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256,
        ),
    )
    for label, path, expected in paths:
        try:
            actual = _canonical_packet_hash(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            actual = f"invalid:{type(error).__name__}"
        if actual != expected:
            findings.append(
                _finding(
                    "PREREQUISITE-IDENTITY-DRIFT",
                    f"{label} canonical identity changed: {actual}.",
                    requirement="P3D-05",
                    evidence=(path.relative_to(root).as_posix(),),
                )
            )
    closure = root / "docs/evals/dashboard-internal-qualification-phase2-closure-rev2.json"
    if closure.is_file() and file_sha256(closure) != PHASE2_CLOSURE_SERIALIZED_SHA256:
        findings.append(
            _finding(
                "PREREQUISITE-SERIALIZATION-DRIFT",
                "Phase 2 closure serialized identity changed.",
                requirement="P3D-05",
                evidence=(closure.relative_to(root).as_posix(),),
            )
        )
    addendum = (
        root
        / "docs/evals/dashboard-internal-qualification-phase2-determinism-addendum-rev2.json"
    )
    if (
        addendum.is_file()
        and file_sha256(addendum) != PHASE2_DETERMINISM_ADDENDUM_SERIALIZED_SHA256
    ):
        findings.append(
            _finding(
                "PREREQUISITE-SERIALIZATION-DRIFT",
                "Phase 2 determinism addendum serialized identity changed.",
                requirement="P3D-05",
                evidence=(addendum.relative_to(root).as_posix(),),
            )
        )
    design_ok, design_actual = verify_design_packet(root)
    if not design_ok or design_actual != PHASE3_DESIGN_CANONICAL_SHA256:
        findings.append(
            _finding(
                "DESIGN-IDENTITY-DRIFT",
                f"Phase 3 design identity changed: {design_actual}.",
                requirement="P3D-10",
            )
        )
    return tuple(findings)


def _write_synthetic_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "qualification-synthetic",
                "schema_version": "project.v1",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / ".scout-workspace-generation.json").write_text(
        json.dumps({"generation_id": "qualification-generation-v1"}, sort_keys=True),
        encoding="utf-8",
    )
    (root / ".scout-qualification-capabilities.json").write_text(
        json.dumps(
            {
                "schema_version": WORKSPACE_CAPABILITY_SCHEMA,
                "capabilities": [
                    {
                        "capability_id": "dashboard.synthetic.current",
                        "schema_version": "v1",
                        "disposition": "direct_support",
                    },
                    {
                        "capability_id": "dashboard.synthetic.historical",
                        "schema_version": "v0",
                        "disposition": "executable_migration",
                    },
                    {
                        "capability_id": "dashboard.synthetic.unknown",
                        "schema_version": "future",
                        "disposition": "typed_quarantine_non_ready",
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _phase2_cases(report: object) -> tuple[Phase3CaseResult, ...]:
    cases: list[Phase3CaseResult] = []
    for item in getattr(report, "obligation_results"):
        accepted = item.status in {"passed", "infeasible"}
        cases.append(
            _case(
                f"phase2:obligation:{item.obligation_id}",
                "retained-phase2-obligation",
                passed=accepted,
                activated=item.status != "not_run",
                not_applicable=item.status == "infeasible",
                evidence=(item.obligation_id, item.status, item.evidence_id),
                finding_codes=tuple(item.finding_ids),
            )
        )
    for item in getattr(report, "replay_results"):
        accepted = item.status in {"passed", "infeasible"}
        cases.append(
            _case(
                f"phase2:replay:{item.replay_id}",
                "retained-phase2-replay",
                passed=accepted,
                activated=item.status != "not_run",
                not_applicable=item.status == "infeasible",
                evidence=(item.replay_id, item.status, item.observed_terminal_id),
            )
        )
    for item in getattr(report, "fault_results"):
        cases.append(
            _case(
                f"phase2:fault:{item.fault_id}",
                "retained-phase2-fault",
                passed=item.status == "passed" and item.activated,
                activated=item.activated,
                evidence=(item.fault_id, item.status, item.execution_identity),
            )
        )
    for item in getattr(report, "concurrency_results"):
        cases.append(
            _case(
                f"phase2:concurrency:{item.schedule_id}",
                "retained-phase2-concurrency",
                passed=item.status == "passed" and item.activated,
                activated=item.activated,
                evidence=(item.schedule_id, item.status, item.execution_identity),
            )
        )
    for item in getattr(report, "mutation_results"):
        cases.append(
            _case(
                f"phase2:mutation:{item.mutant_id}",
                "retained-phase2-mutation",
                passed=item.status == "killed" and item.activated,
                activated=item.activated,
                evidence=(item.mutant_id, item.status, tuple(item.observed_finding_codes)),
                finding_codes=tuple(sorted(set(item.observed_finding_codes))),
            )
        )
    for item in getattr(report, "invariant_results"):
        cases.append(
            _case(
                f"phase2:invariant:{item.invariant_id}",
                "retained-phase2-invariant",
                passed=item.status == "passed",
                activated=item.status != "not_run",
                evidence=(item.invariant_id, item.status, item.evidence_id),
                finding_codes=tuple(item.finding_ids),
            )
        )
    for item in getattr(report, "effect_class_results"):
        cases.append(
            _case(
                f"phase2:effect:{item.effect_class}",
                "retained-phase2-effect",
                passed=item.static_status == "passed" and item.runtime_status == "passed",
                activated=item.runtime_status != "not_run",
                evidence=(item.effect_class, item.static_status, item.runtime_status),
            )
        )
    return tuple(cases)


def _phase2_findings(report: object) -> tuple[Phase3Finding, ...]:
    return tuple(
        Phase3Finding(
            finding_id=f"phase2.{item.finding_id}",
            code=item.code,
            severity=item.severity,
            summary=item.summary,
            requirement_refs=("P3D-05", *item.requirement_refs),
            evidence_refs=item.evidence_refs,
        )
        for item in getattr(report, "findings")
    )


def _production_case(evidence: ProductionReplayEvidence) -> Phase3CaseResult:
    return _case(
        f"replay:{evidence.replay_id}",
        "production-replay",
        passed=evidence.status == "passed",
        activated=True,
        evidence={
            "identity": evidence.identity,
            "terminal": evidence.terminal,
            "output_sha256": evidence.output_sha256,
            "boundary": evidence.boundary,
            "attempted_effect_classes": tuple(
                sorted(set((operation, effect_class, outcome) for operation, effect_class, _, outcome in evidence.attempted_effects))
            ),
            "detail_codes": evidence.detail_codes,
        },
        finding_codes=evidence.detail_codes,
    )


def _verdict(
    cases: Sequence[Phase3CaseResult],
    findings: Sequence[Phase3Finding],
    *,
    complete: bool = True,
) -> tuple[str, bool]:
    if not complete:
        return "invalid", False
    blocking = any(item.severity == "blocking" for item in findings)
    bad_case = any(
        not item.activated or item.status not in {"passed", "not_applicable"}
        for item in cases
    )
    return ("fail" if blocking or bad_case else "pass"), True


def _domain_for_boundary(boundary_id: str) -> str:
    lowered = boundary_id.casefold()
    if "assistant" in lowered:
        return "assistant-planner"
    if "body" in lowered:
        return "body-index-privacy"
    if "observer" in lowered:
        return "observer-hardware-boundary"
    if "permission" in lowered:
        return "contextual-permission"
    return "safety-emergency"


def _sentinel_output_gate(
    reports: Iterable[object],
    tokens: Sequence[tuple[str, str]],
) -> tuple[Phase3Finding, ...]:
    sinks = {sink: [] for sink in PRIVATE_SENTINEL_SINKS}
    rendered = tuple(canonical_json(item) for item in reports)
    for sink in sinks:
        sinks[sink] = rendered
    return scan_private_sentinels(sinks, tokens)


def run_phase3_all_qualification(
    *,
    repository_root: Path,
    execution_root: Path,
    result_root: Path,
    release: bool = False,
    workspace_inventory: Path | None = None,
) -> Phase3RunOutcome:
    repository = Path(repository_root).resolve()
    execution = Path(execution_root).resolve()
    result = Path(result_root).resolve()
    if execution.exists():
        raise ValueError("Phase 3 execution root must not already exist")
    if result.exists():
        raise ValueError("Phase 3 result root must not already exist")
    if release != (workspace_inventory is not None):
        raise ValueError(
            "release requires exactly one explicit --workspace-inventory; construction forbids it"
        )
    execution.mkdir(parents=True)

    prerequisite_findings = list(_verify_prerequisite_files(repository))
    surface: SurfaceDiscovery = discover_dashboard_surface(repository)
    aggregate_findings: list[Phase3Finding] = [
        *prerequisite_findings,
        *surface.findings,
        *validate_default_catalog(repository),
    ]

    if release:
        assert workspace_inventory is not None
        snapshot = inventory_workspace(Path(workspace_inventory).resolve())
    else:
        synthetic_workspace = execution / "synthetic-workspace"
        _write_synthetic_workspace(synthetic_workspace)
        snapshot = inventory_workspace(synthetic_workspace)
    aggregate_findings.extend(validate_workspace_snapshot(snapshot))
    if aggregate_findings:
        codes = tuple(sorted({item.code for item in aggregate_findings}))
        raise ValueError(f"Phase 3 prerequisite or inventory validation failed: {codes!r}")

    phase2 = run_contextual_permission_qualification(
        repository_root=repository,
        execution_root=execution / "phase2-execution",
        result_root=execution / "phase2-result",
    )
    if phase2.exit_code != 0 or phase2.finalized.content_sha256 != PHASE2_REPORT_CANONICAL_SHA256:
        raise ValueError(
            "retained Phase 2 gate changed or failed: "
            f"exit={phase2.exit_code} hash={phase2.finalized.content_sha256}"
        )
    phase2_lineage_contract = load_phase2_lineage_contract(repository)
    phase2_lineage = validate_phase2_lineage(
        phase2_lineage_contract,
        phase2.manifest,
        phase2.finalized.canonical_json,
    )
    if exit_code_for_phase2_lineage(phase2_lineage.findings) != 0:
        raise ValueError(
            "retained Phase 2 full-manifest lineage changed: "
            f"{tuple(sorted({item.code for item in phase2_lineage.findings}))!r}"
        )

    effect_inventory = discover_effect_inventory(repository)
    if effect_inventory.unclassified_callsites:
        raise ValueError(
            f"unclassified effect callsites: {effect_inventory.unclassified_callsites!r}"
        )
    fault_cells = derive_fault_cells(effect_inventory.operations)
    fault_results = run_fault_matrix(
        effect_inventory.operations,
        fault_cells,
        execution_root=execution / "fault-matrix",
        repository_root=repository,
    )
    aggregate_findings.extend(validate_fault_results(fault_cells, fault_results))

    conflict_schedules = derive_conflict_schedules(COMMAND_RESOURCES)
    conflict_results = run_conflict_matrix(
        conflict_schedules,
        execution_root=execution / "command-conflict-matrix",
        repository_root=repository,
    )
    aggregate_findings.extend(
        validate_conflict_results(conflict_schedules, conflict_results)
    )
    dependency_race_schedules = derive_dependency_race_schedules(DEPENDENCY_EDGES)
    dependency_race_results = run_conflict_matrix(
        dependency_race_schedules,
        execution_root=execution / "dependency-race-matrix",
        repository_root=repository,
    )
    aggregate_findings.extend(
        validate_conflict_results(dependency_race_schedules, dependency_race_results)
    )

    dependency_results = tuple(
        run_dependency_case(edge, case_kind)
        for edge in DEPENDENCY_EDGES
        for case_kind in (
            "unchanged",
            "upstream_changed",
            "consumer_missing",
            "consumer_stale",
            "wrong_parent",
            "mixed_generation",
        )
    )
    aggregate_findings.extend(
        validate_dependency_cases(DEPENDENCY_EDGES, dependency_results)
    )

    production_replays = {
        domain_id: run_production_replay(
            domain_id,
            execution_root=execution / f"replay-{domain_id}",
            repository_root=repository,
        )
        for domain_id in DOMAIN_IDS
        if domain_id != "contextual-permission"
    }

    receipt = AuthorityReceipt(
        subject_id="qualification-subject",
        subject_sha256="b" * 64,
        capability_id="qualification-capability.v1",
        generation="qualification-generation-v1",
        actor="operator:qualification",
        policy_version="policy-v1",
        evaluator_version="evaluator-v1",
        scope="synthetic-qualification",
        idempotency_key="qualification-idempotency-v1",
    )
    receipt_findings = validate_authority_receipt(
        receipt,
        expected_subject_id=receipt.subject_id,
        expected_subject_sha256=receipt.subject_sha256,
        expected_generation=receipt.generation,
        expected_policy_version=receipt.policy_version,
        expected_evaluator_version=receipt.evaluator_version,
    )
    aggregate_findings.extend(receipt_findings)
    authority_cases = tuple(
        _case(
            f"authority:{boundary.boundary_id}",
            "authority-boundary",
            passed=(
                (not boundary.allowed)
                or (not boundary.requires_receipt)
                or not receipt_findings
            ),
            evidence={
                "boundary": boundary,
                "forbidden_blocked_before_invocation": not boundary.allowed,
                "receipt_identity": canonical_sha256(receipt) if boundary.requires_receipt else None,
            },
        )
        for boundary in AUTHORITY_BOUNDARIES
    )

    sentinels = tuple(
        {
            *private_sentinel_tokens("body-index-production-replay"),
            *private_sentinel_tokens("observer-production-replay"),
            *private_sentinel_tokens("mutation"),
            *private_sentinel_tokens("phase3-output"),
        }
    )
    safe_sinks = {
        sink: {"status": "redacted", "sentinel_count": 0}
        for sink in PRIVATE_SENTINEL_SINKS
    }
    aggregate_findings.extend(scan_private_sentinels(safe_sinks, sentinels))
    sentinel_cases = tuple(
        _case(
            f"privacy-sentinel:{sink}",
            "private-sentinel",
            passed=True,
            evidence=(sink, "no-sentinel"),
        )
        for sink in PRIVATE_SENTINEL_SINKS
    )

    fault_by_cell = {item.cell_id: item for item in fault_results}
    operation_by_id = {item.operation_id: item for item in effect_inventory.operations}
    for cell in fault_cells:
        if cell.applicability != "not_applicable":
            continue
        operation = operation_by_id[cell.operation_id]
        result_item = fault_by_cell[cell.cell_id]
        risk = next(
            item.risk_profile
            for item in DOMAIN_SPECS
            if item.domain_id == operation.domain_id
        )
        absent_hash = canonical_sha256(
            tuple(
                callsite
                for callsite, operation_id in effect_inventory.callsite_assignments
                if operation_id == operation.operation_id
            )
        )
        witness = NotApplicableWitness(
            witness_id=cell.witness_id or f"infeasible:{cell.cell_id}",
            domain_id=operation.domain_id,
            obligation_id=cell.cell_id,
            risk_profile_sha256=risk.identity,
            absent_callsites_sha256=absent_hash,
            executable_witness_id=result_item.process_identity,
            activated=result_item.activated,
            observed_infeasible=result_item.status == "not_applicable",
        )
        aggregate_findings.extend(
            validate_not_applicable_witness(
                witness,
                expected_risk_profile_sha256=risk.identity,
                expected_absent_callsites_sha256=absent_hash,
            )
        )

    workspace_sha = snapshot.identity
    source_manifest_sha = canonical_sha256(
        {
            "surface": surface.manifest,
            "source_hashes": surface.source_hashes,
            "effects": effect_inventory.source_hashes,
        }
    )
    run_id = (
        "dashboard.phase3."
        + canonical_sha256(
            {
                "claim": "release" if release else "construction",
                "design": PHASE3_DESIGN_CANONICAL_SHA256,
                "phase2": PHASE2_REPORT_CANONICAL_SHA256,
                "phase2_manifest": phase2_lineage.current_manifest_sha256,
                "phase2_manifest_semantic": (
                    phase2_lineage.normalized_manifest_sha256
                ),
                "source": source_manifest_sha,
                "workspace": workspace_sha,
            }
        )[:20]
    )

    command_domain = {item.command_id: item.domain_id for item in COMMAND_RESOURCES}
    edge_by_id = {item.edge_id: item for item in DEPENDENCY_EDGES}
    domain_reports: dict[str, Phase3DomainReport] = {}
    phase2_cases = _phase2_cases(phase2.report)
    phase2_findings = _phase2_findings(phase2.report)
    for spec in DOMAIN_SPECS:
        cases: list[Phase3CaseResult] = []
        findings: list[Phase3Finding] = []
        cases.extend(fixture_case(spec.domain_id, item) for item in spec.fixture_classes)
        cases.append(
            _case(
                f"risk-profile:{spec.domain_id}",
                "risk-profile",
                passed=spec.risk_profile.valid,
                evidence=(spec.risk_profile, spec.risk_profile.derived_minimum_tier),
            )
        )
        for route in spec.ui_routes:
            cases.append(
                _case(
                    f"surface-route:{route}",
                    "surface",
                    passed=route in surface.routes,
                    evidence=(route, spec.domain_id, source_manifest_sha),
                )
            )
        if spec.domain_id == "contextual-permission":
            cases.extend(phase2_cases)
            findings.extend(phase2_findings)
            cases.append(
                _case(
                    "prerequisite:phase2-exact-report",
                    "prerequisite",
                    passed=phase2.finalized.content_sha256 == PHASE2_REPORT_CANONICAL_SHA256,
                    evidence={
                        "joint_closure_report_sha256": (
                            PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256
                        ),
                        "determinism_addendum_sha256": (
                            PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256
                        ),
                        "current_exact_report_sha256": (
                            phase2.finalized.content_sha256
                        ),
                        "current_manifest_sha256": (
                            phase2_lineage.current_manifest_sha256
                        ),
                        "normalized_manifest_sha256": (
                            phase2_lineage.normalized_manifest_sha256
                        ),
                        "normalized_report_sha256": (
                            phase2_lineage.normalized_report_sha256
                        ),
                    },
                )
            )
        else:
            replay = production_replays[spec.domain_id]
            cases.append(_production_case(replay))
            if replay.status != "passed":
                findings.append(
                    _finding(
                        "PRODUCTION-REPLAY-FAILED",
                        f"{replay.replay_id} ended at {replay.terminal}.",
                        requirement="P3D-02",
                        evidence=(replay.identity,),
                    )
                )
        for cell in fault_cells:
            operation = operation_by_id[cell.operation_id]
            if operation.domain_id != spec.domain_id:
                continue
            observed = fault_by_cell[cell.cell_id]
            cases.append(
                _case(
                    cell.cell_id,
                    "effect-fault",
                    passed=observed.status in {"passed", "not_applicable"},
                    activated=observed.activated,
                    not_applicable=observed.status == "not_applicable",
                    evidence=(
                        observed.process_identity,
                        observed.workbench_identity,
                        observed.observed_terminal,
                    ),
                )
            )
        conflict_by_id = {item.schedule_id: item for item in conflict_results}
        for schedule in conflict_schedules:
            if spec.domain_id not in {
                command_domain[schedule.left_command_id],
                command_domain[schedule.right_command_id],
            }:
                continue
            observed = conflict_by_id[schedule.schedule_id]
            cases.append(
                _case(
                    f"domain:{spec.domain_id}:{schedule.schedule_id}",
                    "command-conflict",
                    passed=observed.status == "passed",
                    activated=observed.activated,
                    evidence=(observed.process_identity, observed.workbench_identity, observed.observed_result),
                )
            )
        for dependency in dependency_results:
            edge = edge_by_id[dependency.edge_id]
            if spec.domain_id not in {edge.producer_domain, edge.consumer_domain}:
                continue
            cases.append(
                _case(
                    f"domain:{spec.domain_id}:{dependency.case_id}",
                    "dependency-identity",
                    passed=dependency.status == "passed",
                    activated=dependency.activated,
                    evidence=(
                        dependency.observed_terminal,
                        dependency.producer_identity,
                        dependency.consumer_parent_identity,
                    ),
                )
            )
        dependency_race_by_id = {
            item.schedule_id: item for item in dependency_race_results
        }
        for schedule in dependency_race_schedules:
            edge_id = schedule.schedule_id.split(":", 2)[1]
            edge = edge_by_id[edge_id]
            if spec.domain_id not in {edge.producer_domain, edge.consumer_domain}:
                continue
            observed = dependency_race_by_id[schedule.schedule_id]
            cases.append(
                _case(
                    f"domain:{spec.domain_id}:{schedule.schedule_id}",
                    "dependency-race",
                    passed=observed.status == "passed",
                    activated=observed.activated,
                    evidence=(observed.process_identity, observed.workbench_identity, observed.observed_result),
                )
            )
        cases.extend(
            item
            for item, boundary in zip(authority_cases, AUTHORITY_BOUNDARIES, strict=True)
            if _domain_for_boundary(boundary.boundary_id) == spec.domain_id
        )
        if spec.domain_id in {"body-index-privacy", "observer-hardware-boundary"}:
            cases.extend(sentinel_cases)
        verdict, complete = _verdict(cases, findings)
        domain_reports[spec.domain_id] = Phase3DomainReport(
            schema_version="dashboardQualificationDomainReport.v1",
            run_id=f"{run_id}.{spec.domain_id}",
            aggregate_run_id=run_id,
            domain_id=spec.domain_id,
            source_manifest_sha256=source_manifest_sha,
            domain_model_sha256=spec.identity,
            workspace_snapshot_sha256=workspace_sha,
            verdict=verdict,  # type: ignore[arg-type]
            complete=complete,
            cases=tuple(sorted(cases, key=lambda item: item.case_id)),
            findings=tuple(sorted(findings, key=lambda item: item.finding_id)),
            telemetry=(
                ("case_count", len(cases)),
                ("finding_count", len(findings)),
            ),
        )

    aggregate_cases: list[Phase3CaseResult] = [
        _case(
            "aggregate:design-identity",
            "aggregate",
            passed=True,
            evidence=PHASE3_DESIGN_CANONICAL_SHA256,
        ),
        _case(
            "aggregate:phase2-prerequisite",
            "aggregate",
            passed=True,
            evidence={
                "joint_closure_report_sha256": (
                    PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256
                ),
                "determinism_addendum_sha256": (
                    PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256
                ),
                "current_exact_report_sha256": PHASE2_REPORT_CANONICAL_SHA256,
                "current_manifest_sha256": (
                    phase2_lineage.current_manifest_sha256
                ),
                "normalized_manifest_sha256": (
                    phase2_lineage.normalized_manifest_sha256
                ),
                "normalized_report_sha256": (
                    phase2_lineage.normalized_report_sha256
                ),
            },
        ),
        _case(
            "aggregate:surface-entrypoint-closure",
            "aggregate",
            passed=not surface.findings,
            evidence=surface.identity,
        ),
        _case(
            "aggregate:workspace-seal",
            "aggregate",
            passed=not snapshot.findings and snapshot.before_seal_sha256 == snapshot.after_seal_sha256,
            evidence=snapshot.identity,
        ),
        _case(
            "aggregate:effect-callsite-reconciliation",
            "aggregate",
            passed=not effect_inventory.unclassified_callsites,
            evidence=effect_inventory.identity,
        ),
        _case(
            "aggregate:fault-matrix",
            "aggregate",
            passed=not validate_fault_results(fault_cells, fault_results),
            evidence=(len(fault_cells), len(fault_results)),
        ),
        _case(
            "aggregate:command-conflict-matrix",
            "aggregate",
            passed=not validate_conflict_results(conflict_schedules, conflict_results),
            evidence=(len(conflict_schedules), len(conflict_results)),
        ),
        _case(
            "aggregate:dependency-race-matrix",
            "aggregate",
            passed=not validate_conflict_results(dependency_race_schedules, dependency_race_results),
            evidence=(len(dependency_race_schedules), len(dependency_race_results)),
        ),
        _case(
            "aggregate:dependency-state-matrix",
            "aggregate",
            passed=not validate_dependency_cases(DEPENDENCY_EDGES, dependency_results),
            evidence=(len(DEPENDENCY_EDGES), len(dependency_results)),
        ),
        *authority_cases,
        *sentinel_cases,
    ]
    preliminary_verdict, preliminary_complete = _verdict(
        aggregate_cases,
        aggregate_findings,
    )
    preliminary = Phase3AggregateReport(
        schema_version="dashboardQualificationAggregateReport.v1",
        run_id=run_id,
        claim="release" if release else "construction",
        design_sha256=PHASE3_DESIGN_CANONICAL_SHA256,
        phase2_report_sha256=PHASE2_REPORT_CANONICAL_SHA256,
        repository_identity=surface.manifest.repository_identity,
        source_manifest_sha256=source_manifest_sha,
        workspace_snapshot_sha256=workspace_sha,
        verdict=preliminary_verdict,  # type: ignore[arg-type]
        complete=preliminary_complete,
        required_domain_ids=DOMAIN_IDS,
        domain_report_sha256=tuple(
            (domain_id, canonical_sha256(domain_reports[domain_id]))
            for domain_id in DOMAIN_IDS
        ),
        cases=tuple(sorted(aggregate_cases, key=lambda item: item.case_id)),
        findings=tuple(sorted(aggregate_findings, key=lambda item: item.finding_id)),
    )
    retained_mutants = {
        item.mutant_id: (
            item.activated,
            item.status,
            tuple(item.observed_finding_codes),
        )
        for item in phase2.report.mutation_results
    }
    mutation_results = run_phase3_mutations(
        repository_root=repository,
        execution_root=execution / "mutations",
        surface_manifest=surface.manifest,
        aggregate_report=preliminary,
        domain_reports=domain_reports,
        retained_phase2_mutants=retained_mutants,
    )
    aggregate_cases.extend(mutation_results)
    verdict, complete = _verdict(aggregate_cases, aggregate_findings)
    report = Phase3AggregateReport(
        schema_version="dashboardQualificationAggregateReport.v1",
        run_id=run_id,
        claim="release" if release else "construction",
        design_sha256=PHASE3_DESIGN_CANONICAL_SHA256,
        phase2_report_sha256=PHASE2_REPORT_CANONICAL_SHA256,
        repository_identity=surface.manifest.repository_identity,
        source_manifest_sha256=source_manifest_sha,
        workspace_snapshot_sha256=workspace_sha,
        verdict=verdict,  # type: ignore[arg-type]
        complete=complete,
        required_domain_ids=DOMAIN_IDS,
        domain_report_sha256=tuple(
            (domain_id, canonical_sha256(domain_reports[domain_id]))
            for domain_id in DOMAIN_IDS
        ),
        cases=tuple(sorted(aggregate_cases, key=lambda item: item.case_id)),
        findings=tuple(sorted(aggregate_findings, key=lambda item: item.finding_id)),
        component_sha256=(
            ("design", PHASE3_DESIGN_CANONICAL_SHA256),
            (
                "phase2-joint-closure-report",
                PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256,
            ),
            (
                "phase2-determinism-addendum",
                PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256,
            ),
            ("phase2-manifest", phase2_lineage.current_manifest_sha256),
            ("phase2-manifest-semantic", PHASE2_MANIFEST_SEMANTIC_SHA256),
            ("phase2-report-semantic", PHASE2_REPORT_SEMANTIC_SHA256),
            ("phase2", PHASE2_REPORT_CANONICAL_SHA256),
            ("surface", surface.identity),
            ("effects", effect_inventory.identity),
            ("workspace", workspace_sha),
            ("commands", canonical_sha256(COMMAND_RESOURCES)),
            ("dependencies", canonical_sha256(DEPENDENCY_EDGES)),
            ("mutations", canonical_sha256(mutation_results)),
        ),
        telemetry=(
            ("domain_count", len(domain_reports)),
            ("entrypoint_count", len(surface.manifest.entries)),
            ("effect_operation_count", len(effect_inventory.operations)),
            ("effect_callsite_count", len(effect_inventory.callsite_assignments)),
            ("fault_cell_count", len(fault_cells)),
            ("command_conflict_schedule_count", len(conflict_schedules)),
            ("dependency_case_count", len(dependency_results)),
            ("dependency_race_schedule_count", len(dependency_race_schedules)),
            ("mutation_count", len(mutation_results)),
        ),
    )
    output_findings = _sentinel_output_gate(
        [report, *domain_reports.values()], sentinels
    )
    if output_findings:
        raise ValueError(
            f"private sentinel reached pre-finalization report: {tuple(item.code for item in output_findings)!r}"
        )
    finalized = finalize_phase3_reports(report, domain_reports, result)
    output_paths = (
        finalized.aggregate_json,
        finalized.aggregate_junit,
        finalized.aggregate_text,
        *(
            path
            for _, canonical_path, junit_path, text_path, _ in finalized.domain_outputs
            for path in (canonical_path, junit_path, text_path)
        ),
    )
    for path in output_paths:
        content = path.read_text(encoding="utf-8")
        for _, token in sentinels:
            if token in content:
                raise ValueError(f"private sentinel reached finalized projection: {path.name}")
    exit_code = exit_code_for_phase3(report, domain_reports, finalized=True)
    return Phase3RunOutcome(
        report=report,
        domain_reports=tuple((domain_id, domain_reports[domain_id]) for domain_id in DOMAIN_IDS),
        finalized=finalized,
        exit_code=exit_code,
    )


def run_phase3_domain_qualification(
    domain_id: str,
    *,
    repository_root: Path,
    execution_root: Path,
    result_root: Path,
) -> Phase3DomainRunOutcome:
    if domain_id not in DOMAIN_IDS or domain_id == "contextual-permission":
        raise ValueError(f"Phase 3 focused runner does not own {domain_id}")
    repository = Path(repository_root).resolve()
    execution = Path(execution_root).resolve()
    result = Path(result_root).resolve()
    if execution.exists() or result.exists():
        raise ValueError("focused qualification roots must not already exist")
    execution.mkdir(parents=True)
    prerequisite_findings = (
        *_verify_prerequisite_files(repository),
    )
    surface = discover_dashboard_surface(repository)
    findings: list[Phase3Finding] = [*prerequisite_findings, *surface.findings]
    synthetic_workspace = execution / "synthetic-workspace"
    _write_synthetic_workspace(synthetic_workspace)
    snapshot = inventory_workspace(synthetic_workspace)
    findings.extend(validate_workspace_snapshot(snapshot))
    spec = next(item for item in DOMAIN_SPECS if item.domain_id == domain_id)
    effect_inventory = discover_effect_inventory(repository)
    operations = tuple(
        item for item in effect_inventory.operations if item.domain_id == domain_id
    )
    cells = derive_fault_cells(operations)
    fault_results = run_fault_matrix(
        operations,
        cells,
        execution_root=execution / "fault-matrix",
        repository_root=repository,
    )
    findings.extend(validate_fault_results(cells, fault_results))
    replay = run_production_replay(
        domain_id,
        execution_root=execution / "production-replay",
        repository_root=repository,
    )
    cases: list[Phase3CaseResult] = [
        *(fixture_case(domain_id, fixture) for fixture in spec.fixture_classes),
        _production_case(replay),
        _case(
            f"risk-profile:{domain_id}",
            "risk-profile",
            passed=spec.risk_profile.valid,
            evidence=(spec.risk_profile, spec.risk_profile.derived_minimum_tier),
        ),
        _case(
            "focused:workspace-seal",
            "workspace",
            passed=not snapshot.findings
            and snapshot.before_seal_sha256 == snapshot.after_seal_sha256,
            evidence=snapshot.identity,
        ),
    ]
    for route in spec.ui_routes:
        cases.append(
            _case(
                f"surface-route:{route}",
                "surface",
                passed=route in surface.routes,
                evidence=(route, domain_id, surface.identity),
            )
        )
    result_by_cell = {item.cell_id: item for item in fault_results}
    for cell in cells:
        observed = result_by_cell[cell.cell_id]
        cases.append(
            _case(
                cell.cell_id,
                "effect-fault",
                passed=observed.status in {"passed", "not_applicable"},
                activated=observed.activated,
                not_applicable=observed.status == "not_applicable",
                evidence=(
                    observed.process_identity,
                    observed.workbench_identity,
                    observed.observed_terminal,
                ),
            )
        )
    if replay.status != "passed":
        findings.append(
            _finding(
                "PRODUCTION-REPLAY-FAILED",
                f"{replay.replay_id} ended at {replay.terminal}.",
                requirement="P3D-02",
                evidence=(replay.identity,),
            )
        )
    source_manifest_sha = canonical_sha256(
        {
            "surface": surface.manifest,
            "source_hashes": surface.source_hashes,
            "effects": effect_inventory.source_hashes,
        }
    )
    run_id = f"dashboard.phase3.focused.{domain_id}.{canonical_sha256((source_manifest_sha, snapshot.identity, spec.identity))[:16]}"
    verdict, complete = _verdict(cases, findings)
    report = Phase3DomainReport(
        schema_version="dashboardQualificationDomainReport.v1",
        run_id=run_id,
        aggregate_run_id=run_id,
        domain_id=domain_id,
        source_manifest_sha256=source_manifest_sha,
        domain_model_sha256=spec.identity,
        workspace_snapshot_sha256=snapshot.identity,
        verdict=verdict,  # type: ignore[arg-type]
        complete=complete,
        cases=tuple(sorted(cases, key=lambda item: item.case_id)),
        findings=tuple(sorted(findings, key=lambda item: item.finding_id)),
        telemetry=(
            ("case_count", len(cases)),
            ("effect_operation_count", len(operations)),
            ("fault_cell_count", len(cells)),
        ),
    )
    tokens = tuple(
        {
            *private_sentinel_tokens("body-index-production-replay"),
            *private_sentinel_tokens("observer-production-replay"),
            *private_sentinel_tokens("phase3-output"),
        }
    )
    if _sentinel_output_gate((report,), tokens):
        raise ValueError("private sentinel reached focused report")
    finalized = finalize_phase3_domain_report(report, result)
    for path in (
        finalized.canonical_json,
        finalized.junit_xml,
        finalized.text_report,
    ):
        content = path.read_text(encoding="utf-8")
        if any(token in content for _, token in tokens):
            raise ValueError("private sentinel reached focused finalized output")
    return Phase3DomainRunOutcome(
        report=report,
        finalized=finalized,
        exit_code=exit_code_for_phase3_domain(report, finalized=True),
    )


__all__ = [
    "Phase3DomainRunOutcome",
    "Phase3RunOutcome",
    "run_phase3_all_qualification",
    "run_phase3_domain_qualification",
]
