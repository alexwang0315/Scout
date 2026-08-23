from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from scout.nextgen.max_runtime_preflight import (
    MaxRuntimeReadinessDisposition,
    MaxRuntimeReadinessReport,
    run_max_runtime_preflight,
)
from scout.nextgen.model_qualification import (
    ModelQualificationDisposition,
    build_model_capability_attestation,
    run_openai_compatible_qualification,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight an experimental MAX endpoint and optionally run the full "
            "Scout model qualification packet."
        )
    )
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--preflight-output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=2)
    parser.add_argument("--run-qualification-if-ready", action="store_true")
    parser.add_argument("--case", type=Path)
    parser.add_argument("--evidence-catalog", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--capability-attestation-output", type=Path)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--pythonpath")
    parser.add_argument(
        "--stop-after",
        choices=("basic_chat", "typed_output", "tool_calling"),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (args.case is None) != (args.evidence_catalog is None):
        parser.error("--case and --evidence-catalog must be supplied together")
    if args.run_qualification_if_ready:
        required = {
            "--case": args.case,
            "--evidence-catalog": args.evidence_catalog,
            "--output": args.output,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error(
                "--run-qualification-if-ready requires " + ", ".join(missing)
            )
    preflight = run_max_runtime_preflight(
        runtime_config_path=args.runtime_config,
        timeout_seconds=args.timeout_seconds,
        case_path=args.case,
        evidence_catalog_path=args.evidence_catalog,
        qualification_launcher_path=(
            Path(__file__) if args.case is not None else None
        ),
    )
    _write_model(args.preflight_output, preflight)
    ready = (
        preflight.disposition
        is MaxRuntimeReadinessDisposition.READY_FOR_BEHAVIOR_QUALIFICATION
    )
    if not ready or not args.run_qualification_if_ready:
        _print_result(
            preflight=preflight,
            preflight_output=args.preflight_output,
            qualification_output=None,
            attestation_output=None,
        )
        return _preflight_exit_code(preflight.disposition)

    assert args.case is not None
    assert args.evidence_catalog is not None
    assert args.output is not None
    qualification = run_openai_compatible_qualification(
        runtime_config_path=args.runtime_config,
        case_path=args.case,
        evidence_catalog_path=args.evidence_catalog,
        python_executable=args.python_executable,
        pythonpath=args.pythonpath,
        stop_after=args.stop_after,
    )
    _write_model(args.output, qualification)
    attestation_output: Path | None = None
    if args.capability_attestation_output is not None:
        try:
            attestation = build_model_capability_attestation(qualification)
        except ValueError:
            attestation = None
        if attestation is not None:
            _write_model(args.capability_attestation_output, attestation)
            attestation_output = args.capability_attestation_output
    _print_result(
        preflight=preflight,
        preflight_output=args.preflight_output,
        qualification_output=args.output,
        attestation_output=attestation_output,
    )
    return _qualification_exit_code(qualification.disposition)


def _write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        model.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _print_result(
    *,
    preflight: MaxRuntimeReadinessReport,
    preflight_output: Path,
    qualification_output: Path | None,
    attestation_output: Path | None,
) -> None:
    print(
        json.dumps(
            {
                "preflight_status": preflight.disposition.value,
                "preflight_output": str(preflight_output),
                "qualification_output": (
                    str(qualification_output)
                    if qualification_output is not None
                    else None
                ),
                "capability_attestation_output": (
                    str(attestation_output)
                    if attestation_output is not None
                    else None
                ),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )


def _preflight_exit_code(disposition: MaxRuntimeReadinessDisposition) -> int:
    return {
        MaxRuntimeReadinessDisposition.READY_FOR_BEHAVIOR_QUALIFICATION: 0,
        MaxRuntimeReadinessDisposition.ENDPOINT_UNAVAILABLE: 3,
        MaxRuntimeReadinessDisposition.MODEL_MISMATCH: 4,
        MaxRuntimeReadinessDisposition.HOST_INCOMPATIBLE: 7,
        MaxRuntimeReadinessDisposition.CLI_UNAVAILABLE: 8,
        MaxRuntimeReadinessDisposition.FAILED: 9,
    }[disposition]


def _qualification_exit_code(disposition: ModelQualificationDisposition) -> int:
    return {
        ModelQualificationDisposition.PASSED: 0,
        ModelQualificationDisposition.UNAVAILABLE: 3,
        ModelQualificationDisposition.FAILED: 4,
        ModelQualificationDisposition.PARTIAL: 5,
        ModelQualificationDisposition.TIMED_OUT: 6,
    }[disposition]


if __name__ == "__main__":
    raise SystemExit(main())
