from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Mapping, Sequence

from tests.qualification.contracts import canonical_sha256
from tests.qualification.phase3_catalog import (
    AUTHORITY_BOUNDARIES,
    COMMAND_RESOURCES,
    DEPENDENCY_EDGES,
    DOMAIN_IDS,
    DOMAIN_SPECS,
)
from tests.qualification.phase3_contracts import (
    AuthorityReceipt,
    DashboardExecutableEntrypointManifest,
    NotApplicableWitness,
    Phase3AggregateReport,
    Phase3CaseResult,
    Phase3DomainReport,
)
from tests.qualification.phase3_phase2_lineage import (
    exit_code_for_phase2_lineage,
    load_phase2_lineage_contract,
    phase2_manifest_findings,
)
from tests.qualification.phase3_reporting import (
    InvalidPhase3Qualification,
    exit_code_for_phase3,
    validate_aggregate_report,
)
from tests.qualification.phase3_validation import (
    derive_conflict_schedules,
    private_sentinel_tokens,
    scan_private_sentinels,
    source_derived_dependency_ids,
    validate_authority_flow,
    validate_authority_receipt,
    validate_conflict_schedules,
    validate_dependency_manifest,
    validate_not_applicable_witness,
)
from tests.qualification.phase3_workspace import (
    WORKSPACE_CAPABILITY_SCHEMA,
    inventory_workspace,
    validate_workspace_snapshot,
    validate_workspace_snapshot_reconciliation,
)


def _mutation_result(
    mutant_id: str,
    expected_code: str,
    observed_codes: Sequence[str],
    *,
    activated: bool = True,
) -> Phase3CaseResult:
    observed = tuple(sorted(set(observed_codes)))
    killed = activated and observed == (expected_code,)
    return Phase3CaseResult(
        case_id=f"mutation:{mutant_id}",
        category="mutation",
        status="passed" if killed else "failed",
        activated=activated,
        evidence_ref=canonical_sha256(
            {
                "mutant_id": mutant_id,
                "expected_code": expected_code,
                "observed_codes": observed,
                "activated": activated,
            }
        ),
        finding_codes=observed,
    )


def _write_workspace_capabilities(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "project.json").write_text(
        json.dumps({"project_id": "mutation-synthetic", "schema_version": "project.v1"}),
        encoding="utf-8",
    )
    (root / ".scout-workspace-generation.json").write_text(
        json.dumps({"generation_id": "mutation-generation"}),
        encoding="utf-8",
    )
    (root / ".scout-qualification-capabilities.json").write_text(
        json.dumps(
            {
                "schema_version": WORKSPACE_CAPABILITY_SCHEMA,
                "capabilities": [
                    {
                        "capability_id": "mutation.current",
                        "schema_version": "v1",
                        "disposition": "direct_support",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def run_phase3_mutations(
    *,
    repository_root: Path,
    execution_root: Path,
    surface_manifest: DashboardExecutableEntrypointManifest,
    aggregate_report: Phase3AggregateReport,
    domain_reports: Mapping[str, Phase3DomainReport],
    retained_phase2_mutants: Mapping[str, tuple[bool, str, tuple[str, ...]]],
) -> tuple[Phase3CaseResult, ...]:
    root = Path(execution_root).resolve()
    if root.exists():
        raise ValueError("mutation execution root must not already exist")
    root.mkdir(parents=True)
    results: list[Phase3CaseResult] = []

    for mutant_id, (activated, status, observed_codes) in sorted(
        retained_phase2_mutants.items()
    ):
        unique_codes = tuple(sorted(set(observed_codes)))
        expected = unique_codes[0] if len(unique_codes) == 1 else "PHASE2-MUTANT-NOT-EXACT"
        killed = activated and status == "killed" and len(unique_codes) == 1
        results.append(
            _mutation_result(
                f"retained-phase2:{mutant_id}",
                expected,
                unique_codes,
                activated=killed,
            )
        )

    lineage = load_phase2_lineage_contract(repository_root)
    non_adapter_components = tuple(
        (name, "f" * 64 if name == "engine" else digest)
        for name, digest in lineage.current_manifest.component_sha256
    )
    non_adapter_manifest = dataclasses.replace(
        lineage.current_manifest,
        component_sha256=non_adapter_components,
    )
    non_adapter_findings = phase2_manifest_findings(
        lineage,
        non_adapter_manifest,
    )
    results.append(
        _mutation_result(
            "phase2-non-adapter-manifest-drift-accepted",
            "PHASE2-REGRESSION",
            tuple(
                item.code
                for item in non_adapter_findings
            )
            if exit_code_for_phase2_lineage(non_adapter_findings) == 2
            else (),
        )
    )

    safety = next(item for item in DOMAIN_SPECS if item.domain_id == "safety-emergency")
    downgraded = dataclasses.replace(safety.risk_profile, declared_tier=2)
    results.append(
        _mutation_result(
            "minimum-risk-tier-downgraded",
            "RISK-TIER-DOWNGRADE",
            ("RISK-TIER-DOWNGRADE",) if not downgraded.valid else (),
        )
    )

    shell = next(item for item in DOMAIN_SPECS if item.domain_id == "dashboard-shell-control")
    absent_hash = canonical_sha256(("no-durable-writer",))
    forged_na = NotApplicableWitness(
        witness_id="mutation:forged-na",
        domain_id=shell.domain_id,
        obligation_id="durable-faults",
        risk_profile_sha256=shell.risk_profile.identity,
        absent_callsites_sha256=absent_hash,
        executable_witness_id="",
        activated=False,
        observed_infeasible=False,
    )
    results.append(
        _mutation_result(
            "not-applicable-witness-forged",
            "NOT-APPLICABLE-WITNESS-INVALID",
            tuple(
                item.code
                for item in validate_not_applicable_witness(
                    forged_na,
                    expected_risk_profile_sha256=shell.risk_profile.identity,
                    expected_absent_callsites_sha256=absent_hash,
                )
            ),
        )
    )

    non_route = next(
        item
        for item in surface_manifest.entries
        if item.entrypoint_class not in {"backend_get", "backend_post"}
    )
    mutated_entries = tuple(
        item for item in surface_manifest.entries if item.entrypoint_id != non_route.entrypoint_id
    )
    results.append(
        _mutation_result(
            "non-route-executable-entrypoint-removed",
            "SURFACE-INVENTORY-DRIFT",
            ("SURFACE-INVENTORY-DRIFT",)
            if len(mutated_entries) + 1 == len(surface_manifest.entries)
            else (),
        )
    )

    dependency_codes = tuple(
        item.code
        for item in validate_dependency_manifest(
            DEPENDENCY_EDGES[:-1],
            source_derived_dependency_ids(repository_root),
        )
    )
    results.append(
        _mutation_result(
            "required-cross-domain-edge-removed",
            "DEPENDENCY-INVENTORY-DRIFT",
            dependency_codes,
        )
    )

    schedules = derive_conflict_schedules(COMMAND_RESOURCES)
    first_pair = (schedules[0].left_command_id, schedules[0].right_command_id)
    removed_pair = tuple(
        item
        for item in schedules
        if (item.left_command_id, item.right_command_id) != first_pair
    )
    results.append(
        _mutation_result(
            "required-conflict-pair-removed",
            "COMMAND-CONFLICT-COVERAGE-INCOMPLETE",
            tuple(
                item.code
                for item in validate_conflict_schedules(COMMAND_RESOURCES, removed_pair)
            ),
        )
    )
    results.append(
        _mutation_result(
            "required-shared-yield-removed",
            "COMMAND-CONFLICT-COVERAGE-INCOMPLETE",
            tuple(
                item.code
                for item in validate_conflict_schedules(COMMAND_RESOURCES, schedules[:-1])
            ),
        )
    )

    receipt = AuthorityReceipt(
        subject_id="subject-1",
        subject_sha256="a" * 64,
        capability_id="permission-projection.v1",
        generation="g1",
        actor="operator:synthetic",
        policy_version="policy-v1",
        evaluator_version="evaluator-v1",
        scope="synthetic",
        idempotency_key="idempotency-1",
    )
    subject_codes = tuple(
        item.code
        for item in validate_authority_receipt(
            receipt,
            expected_subject_id="subject-1",
            expected_subject_sha256="b" * 64,
            expected_generation="g1",
            expected_policy_version="policy-v1",
            expected_evaluator_version="evaluator-v1",
        )
    )
    results.append(
        _mutation_result(
            "confirmation-reused-after-subject-change",
            "AUTHORITY-RECEIPT-STALE",
            subject_codes,
        )
    )
    policy_codes = tuple(
        item.code
        for item in validate_authority_receipt(
            receipt,
            expected_subject_id="subject-1",
            expected_subject_sha256="a" * 64,
            expected_generation="g2",
            expected_policy_version="policy-v2",
            expected_evaluator_version="evaluator-v1",
        )
    )
    results.append(
        _mutation_result(
            "admission-reused-after-policy-or-generation-change",
            "AUTHORITY-RECEIPT-STALE",
            policy_codes,
        )
    )

    changing_root = root / "workspace-changing"
    _write_workspace_capabilities(changing_root)
    changing = inventory_workspace(
        changing_root,
        between_seals=lambda path: (path / "project.json").write_text(
            json.dumps({"project_id": "mutation-synthetic", "schema_version": "project.v2"}),
            encoding="utf-8",
        ),
    )
    results.append(
        _mutation_result(
            "workspace-concurrent-mutation-accepted",
            "WORKSPACE-TOCTOU",
            tuple(
                sorted(
                    {
                        item.code
                        for item in validate_workspace_snapshot(changing)
                        if item.code == "WORKSPACE-TOCTOU"
                    }
                )
            ),
        )
    )

    unknown_root = root / "workspace-unknown"
    _write_workspace_capabilities(unknown_root)
    (unknown_root / "unknown-private.bin").write_bytes(b"private sentinel bytes")
    recomputed = inventory_workspace(unknown_root)
    omitted = dataclasses.replace(
        recomputed,
        entries=tuple(item for item in recomputed.entries if item.disposition != "unknown_entry"),
        findings=(),
    )
    results.append(
        _mutation_result(
            "workspace-unknown-entry-omitted",
            "WORKSPACE-INVENTORY-DRIFT",
            tuple(
                item.code
                for item in validate_workspace_snapshot_reconciliation(omitted, recomputed)
            ),
        )
    )

    alias_root = root / "workspace-alias"
    _write_workspace_capabilities(alias_root)
    (alias_root / "alias").symlink_to(alias_root / "project.json")
    alias_snapshot = inventory_workspace(alias_root)
    alias_codes = {
        item.code for item in validate_workspace_snapshot(alias_snapshot)
    }
    results.append(
        _mutation_result(
            "workspace-path-alias-accepted",
            "WORKSPACE-PATH-ALIAS",
            tuple(sorted(code for code in alias_codes if code == "WORKSPACE-PATH-ALIAS")),
        )
    )

    target_domain = DOMAIN_IDS[0]
    mixed = dict(domain_reports)
    mixed[target_domain] = dataclasses.replace(
        mixed[target_domain], aggregate_run_id="foreign-run"
    )
    mixed_codes: tuple[str, ...] = ()
    try:
        validate_aggregate_report(aggregate_report, mixed)
    except InvalidPhase3Qualification:
        mixed_codes = ("AGGREGATE-DOMAIN-IDENTITY-MISMATCH",)
    results.append(
        _mutation_result(
            "stale-foreign-or-mixed-domain-evidence-accepted",
            "AGGREGATE-DOMAIN-IDENTITY-MISMATCH",
            mixed_codes,
        )
    )

    sentinels = private_sentinel_tokens("mutation")
    sentinel_codes = tuple(
        item.code
        for item in scan_private_sentinels(
            {"canonical_json": {"debug": sentinels[0][1]}}, sentinels
        )
    )
    results.append(
        _mutation_result(
            "privacy-sentinel-propagated",
            "PRIVATE-SENTINEL-PROPAGATED",
            sentinel_codes,
        )
    )

    forbidden = next(item for item in AUTHORITY_BOUNDARIES if not item.allowed)
    results.append(
        _mutation_result(
            "authority-candidate-boundary-bypassed",
            "AUTHORITY-BOUNDARY-BYPASS",
            tuple(item.code for item in validate_authority_flow(forbidden, attempted=True)),
        )
    )

    omitted_domains = dict(domain_reports)
    omitted_domains.pop(DOMAIN_IDS[-1])
    omitted_codes: tuple[str, ...] = ()
    try:
        validate_aggregate_report(aggregate_report, omitted_domains)
    except InvalidPhase3Qualification:
        omitted_codes = ("AGGREGATE-DOMAIN-OMITTED",)
    results.append(
        _mutation_result(
            "aggregate-domain-omitted",
            "AGGREGATE-DOMAIN-OMITTED",
            omitted_codes,
        )
    )

    incomplete = dataclasses.replace(
        aggregate_report,
        complete=False,
        verdict="invalid",
    )
    exit_codes = (
        ("AGGREGATE-EXIT-SEMANTICS",)
        if exit_code_for_phase3(incomplete, domain_reports, finalized=True) == 2
        else ()
    )
    results.append(
        _mutation_result(
            "aggregate-incomplete-evidence-exit-zero",
            "AGGREGATE-EXIT-SEMANTICS",
            exit_codes,
        )
    )
    return tuple(results)


__all__ = ["run_phase3_mutations"]
