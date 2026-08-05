from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.qualification.contracts import canonical_sha256
from tests.qualification.phase3_catalog import (
    AUTHORITY_BOUNDARIES,
    COMMAND_RESOURCES,
    DEPENDENCY_EDGES,
    DOMAIN_SPECS,
)
from tests.qualification.phase3_contracts import AuthorityReceipt, NotApplicableWitness
from tests.qualification.phase3_validation import (
    COMMAND_YIELD_POINTS,
    DEPENDENCY_CASE_KINDS,
    derive_conflict_pairs,
    derive_conflict_schedules,
    derive_fault_cells,
    discover_effect_inventory,
    private_sentinel_tokens,
    run_dependency_case,
    scan_private_sentinels,
    source_derived_dependency_ids,
    validate_authority_flow,
    validate_authority_receipt,
    validate_conflict_schedules,
    validate_default_catalog,
    validate_dependency_cases,
    validate_dependency_manifest,
    validate_not_applicable_witness,
)


ROOT = Path(__file__).resolve().parents[2]


def test_current_source_derived_catalog_has_no_validation_findings() -> None:
    assert validate_default_catalog(ROOT) == ()


def test_dependency_matrix_covers_every_edge_and_semantic_case() -> None:
    results = tuple(
        run_dependency_case(edge, case_kind)
        for edge in DEPENDENCY_EDGES
        for case_kind in DEPENDENCY_CASE_KINDS
    )
    assert len(results) == len(DEPENDENCY_EDGES) * len(DEPENDENCY_CASE_KINDS)
    assert validate_dependency_cases(DEPENDENCY_EDGES, results) == ()


def test_removed_dependency_edge_is_detected_against_source_inventory() -> None:
    discovered = source_derived_dependency_ids(ROOT)
    mutated = DEPENDENCY_EDGES[:-1]
    findings = validate_dependency_manifest(mutated, discovered)
    assert "DEPENDENCY-INVENTORY-DRIFT" in {item.code for item in findings}


def test_authority_receipt_stales_on_subject_policy_or_generation_change() -> None:
    receipt = AuthorityReceipt(
        subject_id="subject-1",
        subject_sha256="a" * 64,
        capability_id="permission-projection.v1",
        generation="g1",
        actor="operator:test",
        policy_version="policy-v1",
        evaluator_version="evaluator-v1",
        scope="synthetic:test",
        idempotency_key="idempotency-1",
    )
    assert validate_authority_receipt(
        receipt,
        expected_subject_id="subject-1",
        expected_subject_sha256="a" * 64,
        expected_generation="g1",
        expected_policy_version="policy-v1",
        expected_evaluator_version="evaluator-v1",
    ) == ()
    stale = validate_authority_receipt(
        receipt,
        expected_subject_id="subject-2",
        expected_subject_sha256="b" * 64,
        expected_generation="g2",
        expected_policy_version="policy-v2",
        expected_evaluator_version="evaluator-v1",
    )
    assert {item.code for item in stale} == {"AUTHORITY-RECEIPT-STALE"}


def test_generic_boolean_cannot_replace_identity_bound_receipt() -> None:
    findings = validate_authority_receipt(
        {"confirmed": True},
        expected_subject_id="subject-1",
        expected_subject_sha256="a" * 64,
        expected_generation="g1",
        expected_policy_version="policy-v1",
        expected_evaluator_version="evaluator-v1",
    )
    assert {item.code for item in findings} == {"AUTHORITY-RECEIPT-INCOMPLETE"}


def test_forbidden_candidate_to_runtime_flow_is_blocked() -> None:
    boundary = next(
        item for item in AUTHORITY_BOUNDARIES if item.boundary_id == "assistant-candidate-runtime"
    )
    findings = validate_authority_flow(boundary, attempted=True)
    assert {item.code for item in findings} == {"AUTHORITY-BOUNDARY-BYPASS"}


def test_private_sentinel_scan_covers_all_output_sink_classes() -> None:
    sentinels = private_sentinel_tokens()
    safe = {sink: {"status": "redacted"} for sink in (
        "persisted_artifacts", "findings", "canonical_json", "junit",
        "text_report", "captured_logs", "exception_messages",
    )}
    assert scan_private_sentinels(safe, sentinels) == ()
    unsafe = {**safe, "captured_logs": sentinels[0][1]}
    assert {item.code for item in scan_private_sentinels(unsafe, sentinels)} == {
        "PRIVATE-SENTINEL-PROPAGATED"
    }


def test_effect_inventory_maps_every_discovered_callsite_exactly_once() -> None:
    inventory = discover_effect_inventory(ROOT)
    callsite_ids = tuple(item[0] for item in inventory.callsite_assignments)
    operation_ids = {item.operation_id for item in inventory.operations}
    assert inventory.operations
    assert len(callsite_ids) == len(set(callsite_ids))
    assert all(operation_id in operation_ids for _, operation_id in inventory.callsite_assignments)
    assert inventory.unclassified_callsites == ()
    cells = derive_fault_cells(inventory.operations)
    assert len(cells) == len(inventory.operations) * 3
    assert {item.phase for item in cells} == {"before", "inside", "after"}


def test_command_conflicts_are_mechanically_crossed_with_every_yield() -> None:
    pairs = derive_conflict_pairs(COMMAND_RESOURCES)
    schedules = derive_conflict_schedules(COMMAND_RESOURCES)
    assert pairs
    assert len(schedules) == len(pairs) * len(COMMAND_YIELD_POINTS)
    assert validate_conflict_schedules(COMMAND_RESOURCES, schedules) == ()
    findings = validate_conflict_schedules(COMMAND_RESOURCES, schedules[:-1])
    assert {item.code for item in findings} == {
        "COMMAND-CONFLICT-COVERAGE-INCOMPLETE"
    }


def test_not_applicable_witness_binds_risk_and_absent_callsites() -> None:
    shell = next(item for item in DOMAIN_SPECS if item.domain_id == "dashboard-shell-control")
    absent_hash = canonical_sha256(("no-durable-writer",))
    witness = NotApplicableWitness(
        witness_id="na:shell:durable-faults",
        domain_id=shell.domain_id,
        obligation_id="durable-faults",
        risk_profile_sha256=shell.risk_profile.identity,
        absent_callsites_sha256=absent_hash,
        executable_witness_id="test-shell-no-durable-writer",
        activated=True,
        observed_infeasible=True,
    )
    assert validate_not_applicable_witness(
        witness,
        expected_risk_profile_sha256=shell.risk_profile.identity,
        expected_absent_callsites_sha256=absent_hash,
    ) == ()
    forged = dataclasses.replace(witness, activated=False)
    assert {item.code for item in validate_not_applicable_witness(
        forged,
        expected_risk_profile_sha256=shell.risk_profile.identity,
        expected_absent_callsites_sha256=absent_hash,
    )} == {"NOT-APPLICABLE-WITNESS-INVALID"}
