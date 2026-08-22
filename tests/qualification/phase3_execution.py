from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from tests.qualification.phase3_contracts import (
    ConflictSchedule,
    ConflictScheduleResult,
    EffectFaultCell,
    EffectFaultResult,
    EffectOperation,
)


def _run_worker(arguments: list[str], *, repository_root: Path) -> dict[str, object]:
    process = subprocess.run(
        [sys.executable, "-m", "tests.qualification.phase3_workers", *arguments],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        payload = json.loads(process.stdout.strip())
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"qualification worker emitted invalid JSON (exit={process.returncode})"
        ) from error
    if process.returncode not in {0, 1}:
        raise RuntimeError(
            f"qualification worker invalid (exit={process.returncode}, type={payload.get('error_type')})"
        )
    return payload


def run_fault_matrix(
    operations: Sequence[EffectOperation],
    cells: Sequence[EffectFaultCell],
    *,
    execution_root: Path,
    repository_root: Path,
) -> tuple[EffectFaultResult, ...]:
    root = Path(execution_root).resolve()
    if root.exists():
        raise ValueError("fault matrix execution root must not already exist")
    root.mkdir(parents=True)
    operation_by_id = {item.operation_id: item for item in operations}
    results: list[EffectFaultResult] = []
    for index, cell in enumerate(cells):
        operation = operation_by_id[cell.operation_id]
        args = [
            "fault",
            "--cell-id",
            cell.cell_id,
            "--operation",
            operation.normalized_operation,
            "--phase",
            cell.phase,
            "--workbench",
            str(root / f"cell-{index:04d}"),
        ]
        if cell.applicability == "not_applicable":
            args.append("--prove-infeasible")
        payload = _run_worker(args, repository_root=Path(repository_root).resolve())
        results.append(
            EffectFaultResult(
                cell_id=str(payload.get("cell_id", cell.cell_id)),
                status=str(payload.get("status", "invalid")),  # type: ignore[arg-type]
                activated=bool(payload.get("activated", False)),
                process_identity=str(payload.get("process_identity", "")),
                workbench_identity=str(payload.get("workbench_identity", "")),
                observed_terminal=str(payload.get("observed_terminal", "invalid")),
            )
        )
    return tuple(results)


def run_conflict_matrix(
    schedules: Sequence[ConflictSchedule],
    *,
    execution_root: Path,
    repository_root: Path,
) -> tuple[ConflictScheduleResult, ...]:
    root = Path(execution_root).resolve()
    if root.exists():
        raise ValueError("conflict matrix execution root must not already exist")
    root.mkdir(parents=True)
    results: list[ConflictScheduleResult] = []
    for index, schedule in enumerate(schedules):
        payload = _run_worker(
            [
                "conflict",
                "--schedule-id",
                schedule.schedule_id,
                "--left",
                schedule.left_command_id,
                "--right",
                schedule.right_command_id,
                "--yield-point",
                schedule.yield_point,
                "--workbench",
                str(root / f"schedule-{index:04d}"),
            ],
            repository_root=Path(repository_root).resolve(),
        )
        results.append(
            ConflictScheduleResult(
                schedule_id=str(payload.get("schedule_id", schedule.schedule_id)),
                status=str(payload.get("status", "invalid")),  # type: ignore[arg-type]
                activated=bool(payload.get("activated", False)),
                process_identity=str(payload.get("process_identity", "")),
                workbench_identity=str(payload.get("workbench_identity", "")),
                observed_result=str(payload.get("observed_result", "invalid")),
            )
        )
    return tuple(results)


__all__ = ["run_conflict_matrix", "run_fault_matrix"]
