from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scout.nextgen.model_qualification import (
    ModelQualificationDisposition,
    build_model_capability_attestation,
    run_openai_compatible_qualification,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify one experimental Scout OpenAI-compatible model runtime."
    )
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--evidence-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capability-attestation-output", type=Path)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--pythonpath")
    parser.add_argument(
        "--stop-after",
        choices=("basic_chat", "typed_output", "tool_calling"),
    )
    parser.add_argument(
        "--continue-after-tool-failure",
        action="store_true",
        help=(
            "Collect Praison MCP synthesis evidence after a failed tool gate; "
            "the qualification still fails and cannot produce an attestation."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_openai_compatible_qualification(
        runtime_config_path=args.runtime_config,
        case_path=args.case,
        evidence_catalog_path=args.evidence_catalog,
        python_executable=args.python_executable,
        pythonpath=args.pythonpath,
        stop_after=args.stop_after,
        continue_after_tool_failure=args.continue_after_tool_failure,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)
    attestation_output: str | None = None
    if args.capability_attestation_output is not None:
        try:
            attestation = build_model_capability_attestation(report)
        except ValueError:
            attestation = None
        if attestation is not None:
            args.capability_attestation_output.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            attestation_temporary_path = (
                args.capability_attestation_output.with_suffix(
                    args.capability_attestation_output.suffix + ".tmp"
                )
            )
            attestation_temporary_path.write_text(
                attestation.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            attestation_temporary_path.replace(
                args.capability_attestation_output
            )
            attestation_output = str(args.capability_attestation_output)
    print(
        json.dumps(
            {
                "status": report.disposition.value,
                "runtime_id": report.runtime_id,
                "requested_model_id": report.requested_model_id,
                "report_hash": report.report_hash,
                "output": str(args.output),
                "capability_attestation_output": attestation_output,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    if report.disposition is ModelQualificationDisposition.PASSED:
        return 0
    if report.disposition is ModelQualificationDisposition.UNAVAILABLE:
        return 3
    if report.disposition is ModelQualificationDisposition.TIMED_OUT:
        return 6
    if report.disposition is ModelQualificationDisposition.PARTIAL:
        return 5
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
