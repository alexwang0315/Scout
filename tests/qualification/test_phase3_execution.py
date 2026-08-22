from __future__ import annotations

from pathlib import Path

from tests.qualification.phase3_contracts import EffectOperation
from tests.qualification.phase3_execution import run_conflict_matrix, run_fault_matrix
from tests.qualification.phase3_validation import (
    derive_conflict_schedules,
    derive_fault_cells,
    validate_conflict_results,
    validate_fault_results,
)


ROOT = Path(__file__).resolve().parents[2]


def test_fault_cells_run_in_unique_processes_and_workbenches(tmp_path: Path) -> None:
    operations = (
        EffectOperation("effect:test:write", "workspace-lifecycle", "write", True, "synthetic.py", 1, "path.write_text"),
        EffectOperation("effect:test:http", "assistant-planner", "http", True, "synthetic.py", 2, "httpx.post"),
        EffectOperation("effect:test:read", "dashboard-shell-control", "read", False, "synthetic.py", 3, "path.read_text"),
    )
    cells = derive_fault_cells(operations)
    results = run_fault_matrix(
        operations,
        cells,
        execution_root=tmp_path / "faults",
        repository_root=ROOT,
    )

    assert validate_fault_results(cells, results) == ()
    assert len({item.process_identity for item in results}) == len(results)
    assert len({item.workbench_identity for item in results}) == len(results)
    assert {item.status for item in results} == {"passed", "not_applicable"}


def test_missing_fault_cell_result_is_blocking(tmp_path: Path) -> None:
    operations = (
        EffectOperation("effect:test:write", "workspace-lifecycle", "write", True, "synthetic.py", 1, "path.write_text"),
    )
    cells = derive_fault_cells(operations)
    results = run_fault_matrix(
        operations,
        cells,
        execution_root=tmp_path / "faults",
        repository_root=ROOT,
    )
    findings = validate_fault_results(cells, results[:-1])
    assert "FAULT-COVERAGE-INCOMPLETE" in {item.code for item in findings}


def test_conflict_schedules_run_in_unique_processes_and_fail_stale(tmp_path: Path) -> None:
    schedules = derive_conflict_schedules()[:4]
    results = run_conflict_matrix(
        schedules,
        execution_root=tmp_path / "conflicts",
        repository_root=ROOT,
    )

    assert validate_conflict_results(schedules, results) == ()
    assert {item.observed_result for item in results} == {"serialized-or-stale"}
    assert len({item.process_identity for item in results}) == len(results)
    assert len({item.workbench_identity for item in results}) == len(results)
