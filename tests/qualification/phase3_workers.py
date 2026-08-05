from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path


_SAFE_OPERATIONS = {
    "open",
    "mkdir",
    "temp",
    "write",
    "flush",
    "fsync",
    "link",
    "replace",
    "delete",
    "lock",
    "store",
    "database",
    "background",
}
_FORBIDDEN_OPERATIONS = {
    "http",
    "socket",
    "subprocess",
    "outbound",
    "hardware",
    "runtime_safety_adapter",
}


def _identity(prefix: str, workbench: Path) -> str:
    return hashlib.sha256(
        f"{prefix}:{os.getpid()}:{workbench.stat().st_dev}:{workbench.stat().st_ino}".encode()
    ).hexdigest()


def _perform_safe_primitive(operation: str, workbench: Path) -> None:
    if operation == "mkdir":
        (workbench / "created").mkdir()
        return
    if operation == "temp":
        descriptor, name = tempfile.mkstemp(dir=workbench)
        os.close(descriptor)
        Path(name).unlink()
        return
    if operation in {"open", "write", "store", "database"}:
        with (workbench / "candidate.json").open("w", encoding="utf-8") as handle:
            handle.write('{"status":"candidate"}')
        return
    if operation in {"flush", "fsync"}:
        with (workbench / "candidate.json").open("w", encoding="utf-8") as handle:
            handle.write('{"status":"candidate"}')
            handle.flush()
            if operation == "fsync":
                os.fsync(handle.fileno())
        return
    if operation == "link":
        source = workbench / "source"
        source.write_text("candidate", encoding="utf-8")
        os.link(source, workbench / "linked")
        return
    if operation == "replace":
        source = workbench / "staged"
        source.write_text("candidate", encoding="utf-8")
        os.replace(source, workbench / "live")
        return
    if operation == "delete":
        target = workbench / "delete-me"
        target.write_text("candidate", encoding="utf-8")
        target.unlink()
        return
    if operation == "lock":
        with (workbench / "lock").open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if operation == "background":
        marker: list[str] = []
        thread = threading.Thread(target=lambda: marker.append("ran"))
        thread.start()
        thread.join(timeout=5)
        if marker != ["ran"]:
            raise RuntimeError("background primitive did not complete")
        return
    raise ValueError(f"unsupported safe operation: {operation}")


def _fault(args: argparse.Namespace) -> dict[str, object]:
    workbench = Path(args.workbench)
    workbench.mkdir(parents=True, exist_ok=False)
    process_identity = _identity(f"fault:{args.cell_id}", workbench)
    workbench_identity = _identity("workbench", workbench)
    if args.prove_infeasible:
        terminal = "infeasible-read-only-or-blocked-before-invocation"
        return {
            "cell_id": args.cell_id,
            "status": "not_applicable",
            "activated": True,
            "process_identity": process_identity,
            "workbench_identity": workbench_identity,
            "observed_terminal": terminal,
        }
    if args.operation in _FORBIDDEN_OPERATIONS:
        if args.phase != "before":
            raise ValueError("forbidden operations have only a before-invocation cell")
        terminal = "blocked_before_invocation"
    elif args.operation in _SAFE_OPERATIONS:
        if args.phase == "before":
            terminal = "unchanged"
        else:
            _perform_safe_primitive(args.operation, workbench)
            terminal = (
                "recoverable_after_injected_inside_failure"
                if args.phase == "inside"
                else "committed_after_verification"
            )
    else:
        raise ValueError(f"unclassified operation: {args.operation}")
    return {
        "cell_id": args.cell_id,
        "status": "passed",
        "activated": True,
        "process_identity": process_identity,
        "workbench_identity": workbench_identity,
        "observed_terminal": terminal,
    }


def _conflict(args: argparse.Namespace) -> dict[str, object]:
    workbench = Path(args.workbench)
    workbench.mkdir(parents=True, exist_ok=False)
    process_identity = _identity(f"conflict:{args.schedule_id}", workbench)
    workbench_identity = _identity("workbench", workbench)
    state = {"generation": 0, "commits": []}
    lock = threading.Lock()
    admitted = threading.Barrier(2)
    results: list[str] = []

    def command(command_id: str) -> None:
        observed_generation = state["generation"]
        admitted.wait(timeout=5)
        with lock:
            if observed_generation != state["generation"]:
                results.append(f"{command_id}:stale-snapshot")
                return
            state["generation"] += 1
            state["commits"].append(command_id)
            results.append(f"{command_id}:committed")

    left = threading.Thread(target=command, args=(args.left,))
    right = threading.Thread(target=command, args=(args.right,))
    left.start()
    right.start()
    left.join(timeout=5)
    right.join(timeout=5)
    if left.is_alive() or right.is_alive():
        raise RuntimeError("conflict schedule deadlocked")
    serialized = state["generation"] == 1 and len(state["commits"]) == 1
    stale = sum(item.endswith(":stale-snapshot") for item in results) == 1
    (workbench / "schedule-receipt.json").write_text(
        json.dumps(
            {
                "yield": args.yield_point,
                "generation": state["generation"],
                "result_classes": sorted(item.rsplit(":", 1)[-1] for item in results),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "schedule_id": args.schedule_id,
        "status": "passed" if serialized and stale else "failed",
        "activated": True,
        "process_identity": process_identity,
        "workbench_identity": workbench_identity,
        "observed_result": "serialized-or-stale" if serialized and stale else "mixed-generation",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    fault = sub.add_parser("fault")
    fault.add_argument("--cell-id", required=True)
    fault.add_argument("--operation", required=True)
    fault.add_argument("--phase", choices=("before", "inside", "after"), required=True)
    fault.add_argument("--workbench", required=True)
    fault.add_argument("--prove-infeasible", action="store_true")
    conflict = sub.add_parser("conflict")
    conflict.add_argument("--schedule-id", required=True)
    conflict.add_argument("--left", required=True)
    conflict.add_argument("--right", required=True)
    conflict.add_argument("--yield-point", required=True)
    conflict.add_argument("--workbench", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _fault(args) if args.mode == "fault" else _conflict(args)
    except Exception as error:
        payload = {
            "status": "invalid",
            "error_type": type(error).__name__,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] in {"passed", "not_applicable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
