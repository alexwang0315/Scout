from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.workspace_behavior_model import WorkspaceBehaviorLinearModel
from scout.nextgen.workspace_behavior_qualification import (
    WorkspaceBehaviorQualificationDisposition,
    qualify_workspace_behavior_model,
)
from scout.nextgen.workspace_snapshot import (
    WorkspaceBenchmarkArtifactRole,
    WorkspaceBenchmarkCase,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify a Scout Workspace behavior probe against Frozen Gold."
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--frozen-benchmark", type=Path, required=True)
    parser.add_argument("--qualified-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    model_bytes = args.model.read_bytes()
    model = WorkspaceBehaviorLinearModel.model_validate_json(model_bytes)
    frozen_bytes = args.frozen_benchmark.read_bytes()
    frozen_payload = _load_frozen_benchmark(frozen_bytes)
    cases = tuple(
        WorkspaceBenchmarkCase.model_validate(case) for case in frozen_payload["cases"]
    )
    report = qualify_workspace_behavior_model(
        model=model,
        model_file_sha256=hashlib.sha256(model_bytes).hexdigest(),
        model_file_bytes=len(model_bytes),
        frozen_benchmark_sha256=hashlib.sha256(frozen_bytes).hexdigest(),
        frozen_cases=cases,
        qualified_at=_parse_timestamp(args.qualified_at),
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
                "passed_cases": report.passed_cases,
                "total_cases": report.total_cases,
                "total_latency_us": report.total_latency_us,
                "peak_tracemalloc_bytes": report.peak_tracemalloc_bytes,
                "report_hash": report.report_hash,
                "production_promotion_allowed": (report.production_promotion_allowed),
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return (
        0
        if report.disposition is WorkspaceBehaviorQualificationDisposition.PASSED
        else 4
    )


def _load_frozen_benchmark(raw: bytes) -> dict[str, object]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Frozen Workspace benchmark must be a JSON object")
    if payload.get("schema_version") != "scout.workspace_snapshot_benchmark.v0":
        raise ValueError("unsupported Frozen Workspace benchmark schema")
    if payload.get("artifact_role") != (
        WorkspaceBenchmarkArtifactRole.MODEL_EVALUATION.value
    ):
        raise ValueError("Workspace behavior qualification requires Frozen Gold")
    if payload.get("candidate_only") is not True:
        raise ValueError("Frozen Workspace benchmark must remain candidate-only")
    if payload.get("runtime_safety_truth") is not False:
        raise ValueError("Frozen Workspace benchmark cannot be runtime safety truth")
    declared_hash = payload.get("artifact_hash")
    content = dict(payload)
    content.pop("artifact_hash", None)
    if declared_hash != _canonical_hash(content):
        raise ValueError("Frozen Workspace benchmark artifact hash is invalid")
    if not isinstance(payload.get("cases"), list):
        raise ValueError("Frozen Workspace benchmark cases are missing")
    return payload


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--qualified-at must include a timezone")
    return parsed.astimezone(UTC)


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
