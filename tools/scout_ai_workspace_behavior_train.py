from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scout.nextgen.training_corpus import (
    CorpusPromotionState,
    SyntheticCorpusBundle,
)
from scout.nextgen.workspace_behavior_model import (
    EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY,
    train_workspace_behavior_model,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Train an experimental candidate-only Scout Workspace behavior probe."
        )
    )
    parser.add_argument("--training-corpus", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--training-run-id", required=True)
    parser.add_argument("--trained-at", required=True)
    parser.add_argument("--epochs", type=int, default=4000)
    parser.add_argument("--learning-rate", type=float, default=0.2)
    parser.add_argument("--l2-regularization", type=float, default=0.001)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_bytes = args.training_corpus.read_bytes()
    source, bundle = load_approved_training_corpus(
        source_bytes=source_bytes,
        expected_source_sha256=args.expected_source_sha256,
    )
    review = source["human_review"]
    model = train_workspace_behavior_model(
        training_run_id=args.training_run_id,
        trained_at=_parse_timestamp(args.trained_at),
        source_corpus_sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_artifact_hash=source["artifact_hash"],
        source_review_id=review["review_id"],
        approved_use=review["approved_use"],
        bundle=bundle,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2_regularization=args.l2_regularization,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        model.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)
    print(
        json.dumps(
            {
                "status": "completed",
                "training_run_id": model.training_run_id,
                "training_record_count": model.training_record_count,
                "training_accuracy": model.training_accuracy,
                "initial_loss": model.initial_loss,
                "final_loss": model.final_loss,
                "model_hash": model.model_hash,
                "production_promotion_allowed": (model.production_promotion_allowed),
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return 0


def load_approved_training_corpus(
    *,
    source_bytes: bytes,
    expected_source_sha256: str,
) -> tuple[dict[str, Any], SyntheticCorpusBundle]:
    actual_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if expected_source_sha256 != actual_sha256:
        raise ValueError(
            "training corpus SHA-256 mismatch: "
            f"expected {expected_source_sha256}, got {actual_sha256}"
        )
    payload = json.loads(source_bytes)
    if not isinstance(payload, dict):
        raise ValueError("training corpus must be a JSON object")
    if payload.get("schema_version") != "scout.synthetic_corpus_artifact.v0":
        raise ValueError("unsupported training corpus schema")
    if payload.get("candidate_only") is not True:
        raise ValueError("training corpus must remain candidate-only")
    if payload.get("runtime_safety_truth") is not False:
        raise ValueError("training corpus cannot be runtime safety truth")
    declared_hash = payload.get("artifact_hash")
    content = dict(payload)
    content.pop("artifact_hash", None)
    if declared_hash != _canonical_hash(content):
        raise ValueError("training corpus artifact hash is invalid")

    review = payload.get("human_review")
    if not isinstance(review, dict):
        raise ValueError("training corpus human review is missing")
    if review.get("schema_version") != "scout.synthetic_corpus_human_review.v0":
        raise ValueError("unsupported training corpus human review schema")
    if review.get("approved_use") != (EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY):
        raise ValueError("training corpus approval scope is invalid")
    if review.get("candidate_only") is not True:
        raise ValueError("human review must remain candidate-only")
    if review.get("runtime_safety_truth") is not False:
        raise ValueError("human review cannot be runtime safety truth")
    for field in ("review_id", "review_reference", "reviewed_by", "reviewed_at"):
        value = review.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"training corpus human review {field} is invalid")

    bundle = SyntheticCorpusBundle.model_validate(payload.get("bundle"))
    if not bundle.records:
        raise ValueError("training corpus contains no records")
    if any(
        record.promotion_state is not CorpusPromotionState.TRAINING_ELIGIBLE
        for record in bundle.records
    ):
        raise ValueError("training corpus contains an ineligible record")
    if payload.get("training_eligible_count") != len(bundle.records):
        raise ValueError("training corpus eligible count is inconsistent")

    approved_hashes = review.get("approved_record_hashes")
    promoted_records = review.get("promoted_records")
    if not isinstance(approved_hashes, list) or not isinstance(
        promoted_records,
        list,
    ):
        raise ValueError("training corpus review hash bindings are missing")
    promoted_hashes = {
        item.get("promoted_record_hash")
        for item in promoted_records
        if isinstance(item, dict)
    }
    source_hashes = {
        item.get("source_record_hash")
        for item in promoted_records
        if isinstance(item, dict)
    }
    if promoted_hashes != {record.record_hash for record in bundle.records}:
        raise ValueError("training corpus promoted record binding is invalid")
    if source_hashes != set(approved_hashes):
        raise ValueError("training corpus approved record binding is invalid")
    return payload, bundle


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--trained-at must include a timezone")
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
