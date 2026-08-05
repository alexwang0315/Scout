from __future__ import annotations

import ast
import dataclasses
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scout_contextual_permission_workbench import (
    ContextualPermissionWorkbench,
    build_reference_workbench_seed,
)

from tests.qualification.contextual_permission_phase1 import (
    load_permission_trace,
)
from tests.qualification.contracts import ObservationValue
from tests.qualification.coverage import (
    detect_projection_collisions,
    reconcile_historical_inventory,
)
from tests.qualification.domains.contextual_permission_adapter import (
    run_changed_upstream_identity_schedule,
    run_projection_cleanup_fault,
    run_production_test,
    run_recovery_race_schedule,
    run_rebuild_concurrency_schedule,
    run_serialized_rebuild_write_schedule,
    run_writer_fault_matrix,
)
from tests.qualification.domains.contextual_permission_history import (
    discover_historical_capabilities,
)
from tests.qualification.domains.contextual_permission_oracle import (
    UnknownContextualPermissionObservation,
    envelope_from_independent_state,
    observe_isolated_project,
    project_contextual_permission_state,
)
from tests.qualification.domains.contextual_permission_runner import (
    build_default_contextual_permission_model,
    run_contextual_permission_qualification,
)
from tests.qualification.effects import (
    discover_python_effect_callsites,
    discover_python_sensitive_imports,
    run_absent_effect_canaries,
    validate_effect_attempts,
    validate_effect_class_results,
    validate_static_effect_surface,
)
from tests.qualification.engine import validate_domain_model
from tests.qualification.explorer import explore_domain
from tests.qualification.reporting import (
    load_finalized_report,
    projection_blocking_inventory,
)
from tests.test_scout_contextual_permission_workbench_api import (
    NOW,
    PROJECT_ID,
    _client,
)


REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "contextual_permission"


def test_permission_model_is_valid_complete_and_historically_reconciled() -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    assert validate_domain_model(model) == ()
    exploration = explore_domain(model)
    assert exploration.findings == ()
    assert set(exploration.reachable_state_ids) >= set(
        model.supported_start_state_ids
    )
    assert reconcile_historical_inventory(
        model.historical_inventory,
        discover_historical_capabilities(REPOSITORY_ROOT),
    ) == ()
    assert model.equivalence_rules == (
        (
            "equivalence.isomorphic-isolated-workspace-identities",
            (
                "/artifact_identity",
                "/parent_identities",
                "/command_snapshot_sha256",
            ),
        ),
    )


def test_effect_surface_reconciles_every_callsite_and_absent_class_canary(
    tmp_path: Path,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)
    refs = (
        "scout_contextual_permission_workbench.py",
        "scout_contextual_permission_workbench_api.py",
    )
    callsites = tuple(
        sorted(
            (
                item
                for ref in refs
                for item in discover_python_effect_callsites(
                    REPOSITORY_ROOT / ref,
                    source_ref=ref,
                )
            ),
            key=lambda item: item.callsite_id,
        )
    )
    static_evidence = tuple(
        sorted(
            {
                *(item.signature for item in callsites),
                *(
                    item
                    for ref in refs
                    for item in discover_python_sensitive_imports(
                        REPOSITORY_ROOT / ref
                    )
                ),
            }
        )
    )

    assert callsites == model.effect_surface.callsites
    assert callsites
    assert not any(item.operation == "unclassified" for item in callsites)
    assert validate_static_effect_surface(
        model.effect_surface,
        static_evidence,
        callsites,
    ) == ()

    results, attempts = run_absent_effect_canaries(
        model.effect_surface,
        execution_root=tmp_path / "effect-canaries",
        discovered_calls=static_evidence,
    )

    assert len(results) == 7
    assert validate_effect_class_results(model.effect_surface, results) == ()
    assert validate_effect_attempts(model.effect_surface, attempts) == ()
    assert all(
        item.outcome == "blocked_before_invocation" and item.canary_id
        for item in attempts
    )


def test_fault_and_concurrency_matrix_validators_reject_one_missing_cell() -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)
    broken_fault_surface = dataclasses.replace(
        model.effect_surface,
        fault_coverage=model.effect_surface.fault_coverage[:-1],
    )
    broken_fault_model = dataclasses.replace(
        model,
        effect_surface=broken_fault_surface,
    )
    assert "FAULT-MATRIX-INCOMPLETE" in {
        item.code for item in validate_domain_model(broken_fault_model)
    }

    broken_concurrency_model = dataclasses.replace(
        model,
        required_concurrency_schedules=(
            model.required_concurrency_schedules[:-1]
        ),
    )
    assert "CONCURRENCY-MATRIX-INCOMPLETE" in {
        item.code for item in validate_domain_model(broken_concurrency_model)
    }


def test_oracle_and_model_dependency_direction_excludes_production_semantics() -> None:
    domain_root = Path(__file__).parent / "domains"
    audited = {
        "model": domain_root / "contextual_permission_model.py",
        "oracle": domain_root / "contextual_permission_oracle.py",
    }
    for role, path in audited.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            str(node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not any(
            name.startswith("scout_contextual_permission")
            or name in {"admin_api", "tests.qualification.contextual_permission_adapter"}
            for name in imports
        ), (role, imports)
        if role == "oracle":
            assert not any(name.endswith("contextual_permission_adapter") for name in imports)

    generic_paths = tuple(
        Path(__file__).parent / name
        for name in (
            "contracts.py",
            "coverage.py",
            "effects.py",
            "engine.py",
            "explorer.py",
            "reporting.py",
        )
    )
    for path in generic_paths:
        source = path.read_text(encoding="utf-8")
        assert "scout_contextual_permission" not in source
        assert "contextual_permission_adapter" not in source
        assert "admin_api" not in source
    adapter_source = (
        domain_root / "contextual_permission_adapter.py"
    ).read_text(encoding="utf-8")
    assert "contextual_permission_oracle" not in adapter_source


def test_oracle_rejects_unknown_semantic_value_without_coercion() -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)
    trace = load_permission_trace(FIXTURE_ROOT / "supported_state_catalog.json")
    envelope = envelope_from_independent_state(
        trace.states[0],
        source_id="fixture.no-baseline",
        adapter_sha256="a" * 64,
        model=model,
    )
    mutated_fields = tuple(
        ObservationValue.from_value(
            path=item.path,
            provenance=item.provenance,
            value="future-capability.v99",
        )
        if item.path == "/baseline_capability"
        else item
        for item in envelope.fields
    )

    with pytest.raises(UnknownContextualPermissionObservation):
        project_contextual_permission_state(
            dataclasses.replace(envelope, fields=mutated_fields),
            model=model,
        )


def test_named_identity_equivalence_does_not_hide_semantic_collision() -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)
    trace = load_permission_trace(FIXTURE_ROOT / "supported_state_catalog.json")
    ready = next(item for item in trace.states if item.state_id == "qualified-ready")
    projected = next(item for item in model.states if item.state_id == "qualified-ready")
    first = envelope_from_independent_state(
        dataclasses.replace(ready, artifact_identity="a" * 64),
        source_id="ready.first",
        adapter_sha256="b" * 64,
        model=model,
    )
    second = envelope_from_independent_state(
        dataclasses.replace(ready, artifact_identity="c" * 64),
        source_id="ready.second",
        adapter_sha256="b" * 64,
        model=model,
    )
    assert detect_projection_collisions(
        model,
        ((first, projected), (second, projected)),
    ) == ()

    stale = envelope_from_independent_state(
        dataclasses.replace(
            ready,
            artifact_identity="d" * 64,
            baseline_review_binding="stale",
        ),
        source_id="ready.semantic-mutant",
        adapter_sha256="b" * 64,
        model=model,
    )
    assert [
        item.code
        for item in detect_projection_collisions(
            model,
            ((first, projected), (stale, projected)),
        )
    ] == ["PROJECTION-COLLISION"]


def test_real_production_replay_reaches_independently_observed_ready(
    tmp_path: Path,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)
    execution = run_production_test(
        "test_projection_absent_start_replays_domain_rebuild_to_ready",
        execution_root=tmp_path / "replay",
        repository_root=REPOSITORY_ROOT,
    )

    assert execution.status == "passed", execution.detail
    observed = observe_isolated_project(
        execution.project_root,
        source_id="replay.projection-absent",
        adapter_sha256="b" * 64,
        model=model,
    )
    assert observed.state.state_id == "qualified-ready"
    assert observed.state.terminal_id == "terminal.ready"
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()
    assert execution.effect_attempts


@pytest.mark.parametrize(
    "runner_id",
    (
        "phase2.transition.author-legacy-candidate",
        "phase2.transition.provide-proposal-inputs-from-candidate",
    ),
)
def test_transition_specific_candidate_replays_execute_real_commands(
    tmp_path: Path,
    runner_id: str,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    execution = run_production_test(
        runner_id,
        execution_root=tmp_path / runner_id,
        repository_root=REPOSITORY_ROOT,
    )

    assert execution.status == "passed", execution.detail
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


@pytest.mark.parametrize(
    ("schedule_id", "expected"),
    (
        ("schedule.same-snapshot-same-key.admission", "shared-receipt"),
        (
            "schedule.same-snapshot-different-key.admission",
            "one-winner-one-snapshot-conflict",
        ),
    ),
)
def test_rebuild_concurrency_uses_deterministic_barrier_before_store_lock(
    tmp_path: Path,
    schedule_id: str,
    expected: str,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    execution = run_rebuild_concurrency_schedule(
        schedule_id,
        execution_root=tmp_path / schedule_id,
        repository_root=REPOSITORY_ROOT,
    )

    assert execution.status == "passed", execution.detail
    assert execution.observed_result == expected
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


def test_different_key_concurrency_report_is_stable_regardless_of_winner(
    tmp_path: Path,
) -> None:
    schedule_id = "schedule.same-snapshot-different-key.admission"

    first = run_rebuild_concurrency_schedule(
        schedule_id,
        execution_root=tmp_path / "first",
        repository_root=REPOSITORY_ROOT,
    )
    second = run_rebuild_concurrency_schedule(
        schedule_id,
        execution_root=tmp_path / "second",
        repository_root=REPOSITORY_ROOT,
    )

    assert first.status == second.status == "passed"
    assert first.detail == second.detail
    results = json.loads(first.detail)["results"]
    assert results[0][0] == "passed"
    assert len(results[0][1]) == 64
    assert results[1] == ["rejected", "projection_rebuild_snapshot_conflict"]


def test_replace_writer_cleans_partial_temp_on_inside_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store_root = _client(tmp_path)
    project_root = tmp_path / "workspace" / PROJECT_ID
    workbench = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
        seed_override=build_reference_workbench_seed(PROJECT_ID),
        allow_stale_projection=True,
    )
    target = project_root / "outputs/qualification-fault-target.json"
    original_fdopen = os.fdopen

    class PartialWriteHandle:
        def __init__(self, handle: object) -> None:
            self.handle = handle

        def __enter__(self) -> "PartialWriteHandle":
            return self

        def __exit__(self, *args: object) -> None:
            self.handle.close()

        def write(self, data: bytes) -> int:
            self.handle.write(data[:8])
            raise OSError("injected inside-write failure")

        def flush(self) -> None:
            self.handle.flush()

        def fileno(self) -> int:
            return self.handle.fileno()

    def partial_fdopen(*args: object, **kwargs: object) -> PartialWriteHandle:
        return PartialWriteHandle(original_fdopen(*args, **kwargs))

    monkeypatch.setattr(os, "fdopen", partial_fdopen)

    with pytest.raises(OSError, match="inside-write"):
        workbench._write_replace_json(target, {"status": "complete"})

    assert not target.exists()
    assert not tuple(target.parent.glob(".qualification-fault-target.json.tmp-*"))


def test_append_writer_recovers_one_transient_temp_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store_root = _client(tmp_path)
    project_root = tmp_path / "workspace" / PROJECT_ID
    workbench = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
        seed_override=build_reference_workbench_seed(PROJECT_ID),
        allow_stale_projection=True,
    )
    target = project_root / "outputs/qualification-append-cleanup.json"
    original_unlink = Path.unlink
    fault_activated = False

    def fail_first_temp_cleanup(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal fault_activated
        if (
            not fault_activated
            and path.name.startswith(f".{target.name}.tmp-")
        ):
            fault_activated = True
            raise OSError("injected transient temp cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_temp_cleanup)

    workbench._write_new_json(target, {"state": "after"})

    assert fault_activated is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "after"}
    assert not tuple(target.parent.glob(f".{target.name}.tmp-*"))


def test_writer_fault_matrix_covers_inside_primitives_from_fresh_workbenches(
    tmp_path: Path,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    execution = run_writer_fault_matrix(
        fault_specs=model.required_faults,
        execution_root=tmp_path / "writer-faults",
        repository_root=REPOSITORY_ROOT,
    )

    assert len(execution.results) == 24
    assert all(item.status == "passed" for item in execution.results), tuple(
        (item.fault_id, item.detail) for item in execution.results
    )
    assert all(item.activated for item in execution.results)
    assert len({item.execution_identity for item in execution.results}) == 24
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


def test_projection_transaction_cleanup_failure_is_typed_and_exact_key_recovers(
    tmp_path: Path,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    execution = run_projection_cleanup_fault(
        execution_root=tmp_path / "projection-cleanup-fault",
        repository_root=REPOSITORY_ROOT,
    )

    assert len(execution.results) == 1
    assert execution.results[0].status == "passed", execution.results[0].detail
    assert execution.results[0].observed_terminal_kind == "write_in_doubt"
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


def test_recovery_race_allows_exact_recovery_and_rejects_new_command(
    tmp_path: Path,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    execution = run_recovery_race_schedule(
        execution_root=tmp_path / "recovery-race",
        repository_root=REPOSITORY_ROOT,
    )

    assert execution.status == "passed", execution.detail
    assert execution.observed_result == "recovery-wins-new-command-rejected"
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


def test_changed_upstream_identity_is_a_real_interleaved_stale_rejection(
    tmp_path: Path,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)

    execution = run_changed_upstream_identity_schedule(
        execution_root=tmp_path / "upstream-race",
        repository_root=REPOSITORY_ROOT,
    )

    assert execution.status == "passed", execution.detail
    assert execution.observed_result == "changed-upstream-stale-command-rejected"
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


def test_store_lock_serializes_contender_through_every_rebuild_write_yield(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = build_default_contextual_permission_model(REPOSITORY_ROOT)
    monkeypatch.chdir(tmp_path)

    execution = run_serialized_rebuild_write_schedule(
        conflict_pair_id="pair.same-snapshot-different-key",
        yield_point="journal-creation",
        execution_root=Path("durable-write-schedule"),
        repository_root=REPOSITORY_ROOT,
    )

    assert execution.status == "passed", execution.detail
    assert execution.observed_result == "different-key-typed-prelock-rejection"
    assert execution.activated is True
    assert json.loads(execution.detail)["observed_yields"] == [
        "journal-creation",
        "planned-eta-write",
        "rules-write",
        "seed-write",
        "stale-marker-write",
        "project-pointer-activation",
        "receipt-write",
        "journal-cleanup",
    ]
    assert validate_effect_attempts(model.effect_surface, execution.effect_attempts) == ()


def test_phase2_runner_finalizes_one_authoritative_passing_report(
    tmp_path: Path,
) -> None:
    outcome = run_contextual_permission_qualification(
        repository_root=REPOSITORY_ROOT,
        execution_root=tmp_path / "execution",
        result_root=tmp_path / "result",
    )

    assert outcome.exit_code == 0, tuple(
        (item.code, item.summary) for item in outcome.report.findings
    )
    assert outcome.report.verdict == "pass"
    assert outcome.report.complete is True
    assert len(outcome.report.replay_results) == 10
    assert len(outcome.report.effect_class_results) == 7
    assert len(outcome.report.fault_results) == 27
    assert len(outcome.report.concurrency_results) == 28
    assert len(outcome.report.mutation_results) == 11
    assert {
        item.mutant_id for item in outcome.report.mutation_results
    } >= {
        "mutant.omitted-semantic-observation-field",
        "mutant.required-transition-removed",
    }
    assert all(
        item.activated and item.execution_identity
        for item in outcome.report.fault_results
    )
    assert len(
        {item.execution_identity for item in outcome.report.fault_results}
    ) == len(outcome.report.fault_results)
    assert all(
        item.activated and item.execution_identity
        for item in outcome.report.concurrency_results
    )
    assert len(
        {item.execution_identity for item in outcome.report.concurrency_results}
    ) == len(outcome.report.concurrency_results)
    assert all(
        item.activated and item.status == "killed"
        for item in outcome.report.mutation_results
    )
    assert all(
        status in {"passed", "infeasible"}
        for _, status in outcome.report.coverage_inventory
    )
    assert all(
        item.status == "passed" for item in outcome.report.invariant_results
    )
    assert load_finalized_report(outcome.finalized.canonical_json) == outcome.report
    assert projection_blocking_inventory(outcome.finalized.junit_xml) == ()
    assert projection_blocking_inventory(outcome.finalized.text_report) == ()
    junit_cases = {
        item.attrib["name"]
        for item in ET.parse(outcome.finalized.junit_xml).findall(".//testcase")
    }
    assert junit_cases == {
        *(f"obligation:{item.obligation_id}" for item in outcome.report.obligation_results),
        *(f"invariant:{item.invariant_id}" for item in outcome.report.invariant_results),
        *(f"replay:{item.replay_id}" for item in outcome.report.replay_results),
        *(
            f"effect-class:{item.effect_class}"
            for item in outcome.report.effect_class_results
        ),
        *(f"fault:{item.fault_id}" for item in outcome.report.fault_results),
        *(
            f"concurrency:{item.schedule_id}"
            for item in outcome.report.concurrency_results
        ),
        *(f"mutation:{item.mutant_id}" for item in outcome.report.mutation_results),
    }
    assert len(junit_cases) == 120
