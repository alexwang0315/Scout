from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.workspace_training_gate import (
    WorkspaceTrainingGateDisposition,
    run_workspace_training_gate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Scout Workspace model training promotion gates."
    )
    parser.add_argument("--frozen-benchmark", type=Path, required=True)
    parser.add_argument("--model-report", type=Path, required=True)
    parser.add_argument("--training-corpus", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_workspace_training_gate(
        frozen_benchmark_path=args.frozen_benchmark,
        model_report_path=args.model_report,
        training_corpus_path=args.training_corpus,
        generated_at=_parse_timestamp(args.generated_at),
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
                "ready_for_experimental_training": (
                    report.ready_for_experimental_training
                ),
                "failed_check_ids": report.failed_check_ids,
                "training_record_count": report.training_record_count,
                "training_eligible_count": report.training_eligible_count,
                "report_hash": report.report_hash,
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    if (
        report.disposition
        is WorkspaceTrainingGateDisposition.READY_FOR_EXPERIMENTAL_TRAINING
    ):
        return 0
    if report.disposition in {
        WorkspaceTrainingGateDisposition.BLOCKED_HUMAN_REVIEW,
        WorkspaceTrainingGateDisposition.BLOCKED_MODEL_QUALITY,
    }:
        return 5
    return 4


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
