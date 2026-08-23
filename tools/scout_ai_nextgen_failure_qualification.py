from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.failure_qualification import build_nextgen_failure_matrix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute the Scout NextGen fail-closed qualification matrix."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-executable", default=sys.executable)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    matrix = build_nextgen_failure_matrix()
    node_ids = tuple(
        dict.fromkeys(
            node_id
            for case in matrix.cases
            for node_id in case.probe_node_ids
        )
    )
    command = (
        args.python_executable,
        "-m",
        "pytest",
        "-q",
        *node_ids,
    )
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    attempts: list[dict[str, object]] = []
    final_returncode = 1
    for attempt_number in (1, 2):
        attempt_started_at = datetime.now(UTC)
        attempt_started_monotonic = time.monotonic()
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        combined_output = completed.stdout + completed.stderr
        output_lines = [
            line for line in combined_output.splitlines() if line.strip()
        ]
        attempts.append(
            {
                "attempt": attempt_number,
                "status": "passed" if completed.returncode == 0 else "failed",
                "started_at": attempt_started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "latency_ms": int(
                    (time.monotonic() - attempt_started_monotonic) * 1000
                ),
                "exit_code": completed.returncode,
                "output_hash": hashlib.sha256(
                    combined_output.encode("utf-8")
                ).hexdigest(),
                "summary": output_lines[-1] if output_lines else "no pytest output",
                "failure_diagnostic_tail": (
                    output_lines[-40:] if completed.returncode != 0 else []
                ),
            }
        )
        final_returncode = completed.returncode
        if final_returncode == 0:
            break
    completed_at = datetime.now(UTC)
    final_status = (
        "failed"
        if final_returncode != 0
        else (
            "passed"
            if len(attempts) == 1
            else "passed_after_bounded_retry"
        )
    )
    artifact = {
        "schema_version": "scout.nextgen_failure_qualification.v0",
        "generated_at": completed_at.isoformat(),
        "matrix": matrix.model_dump(mode="json"),
        "execution": {
            "status": final_status,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "latency_ms": int((time.monotonic() - started_monotonic) * 1000),
            "probe_count": len(node_ids),
            "probe_node_ids": node_ids,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "exit_code": final_returncode,
            "summary": attempts[-1]["summary"],
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    artifact["artifact_hash"] = _canonical_hash(artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)
    print(
        json.dumps(
            {
                "status": artifact["execution"]["status"],
                "scenario_count": len(matrix.cases),
                "probe_count": len(node_ids),
                "summary": artifact["execution"]["summary"],
                "artifact_hash": artifact["artifact_hash"],
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return final_returncode


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
