from __future__ import annotations

import argparse
import json
from pathlib import Path

from scout.nextgen.workspace_model_benchmark import (
    WorkspaceModelBenchmarkDisposition,
    run_workspace_model_benchmark,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Scout Workspace dependency benchmark on one model."
    )
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--workspace-benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--max-output-tokens", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_workspace_model_benchmark(
        runtime_config_path=args.runtime_config,
        workspace_benchmark_path=args.workspace_benchmark,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)
    print(
        json.dumps(
            {
                "status": report.disposition.value,
                "runtime_id": report.runtime_id,
                "model_id": report.model_id,
                "workspace_dependency_score": (
                    report.metrics.workspace_dependency_score
                ),
                "passed_cases": report.metrics.passed_cases,
                "total_cases": report.metrics.total_cases,
                "total_model_requests": report.metrics.total_model_requests,
                "total_model_latency_ms": (
                    report.metrics.total_model_latency_ms
                ),
                "report_hash": report.report_hash,
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    if report.disposition is WorkspaceModelBenchmarkDisposition.PASSED:
        return 0
    if report.disposition is WorkspaceModelBenchmarkDisposition.PARTIAL:
        return 5
    if report.disposition is WorkspaceModelBenchmarkDisposition.UNAVAILABLE:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
