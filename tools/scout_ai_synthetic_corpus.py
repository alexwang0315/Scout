from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.training_corpus import SyntheticScenarioGenerator
from scout.nextgen.workspace_snapshot import WorkspaceBenchmarkCase


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a verified candidate Scout synthetic corpus bundle."
    )
    parser.add_argument("--workspace-benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    generated_at = _parse_timestamp(args.generated_at)
    source_bytes = args.workspace_benchmark.read_bytes()
    source = json.loads(source_bytes)
    _validate_source_artifact(source)
    benchmark_cases = tuple(
        WorkspaceBenchmarkCase.model_validate(case) for case in source["cases"]
    )
    bundle = SyntheticScenarioGenerator().generate(
        benchmark_cases=benchmark_cases,
        generated_at=generated_at,
    )
    artifact = {
        "schema_version": "scout.synthetic_corpus_artifact.v0",
        "generated_at": generated_at.isoformat(),
        "source_workspace_benchmark": str(args.workspace_benchmark),
        "source_workspace_benchmark_sha256": hashlib.sha256(
            source_bytes
        ).hexdigest(),
        "bundle": bundle.model_dump(mode="json"),
        "training_eligible_count": sum(
            record.promotion_state.value == "training_eligible"
            for record in bundle.records
        ),
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
                "status": "passed",
                "record_count": len(bundle.records),
                "training_eligible_count": 0,
                "artifact_hash": artifact["artifact_hash"],
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return 0


def _validate_source_artifact(source: dict[str, object]) -> None:
    if source.get("schema_version") != "scout.workspace_snapshot_benchmark.v0":
        raise ValueError("unsupported Workspace benchmark schema")
    if source.get("candidate_only") is not True:
        raise ValueError("Workspace benchmark must remain candidate-only")
    if source.get("runtime_safety_truth") is not False:
        raise ValueError("Workspace benchmark cannot be runtime safety truth")
    declared_hash = source.get("artifact_hash")
    hash_payload = dict(source)
    hash_payload.pop("artifact_hash", None)
    if declared_hash != _canonical_hash(hash_payload):
        raise ValueError("Workspace benchmark artifact hash is invalid")
    if not isinstance(source.get("cases"), list):
        raise ValueError("Workspace benchmark cases are missing")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
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
