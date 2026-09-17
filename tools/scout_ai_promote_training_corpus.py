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
    promote_training_record,
    verify_training_record,
)


EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY = (
    "experimental_workspace_behavior_training_only"
)
PROMOTION_VERIFIER_ID = "scout.workspace_training.human_review_promotion.v0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote an exact, human-approved Scout corpus hash set for "
            "experimental Workspace behavior training only."
        )
    )
    parser.add_argument("--source-corpus", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--approved-record-hash", action="append", required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--review-reference", required=True)
    parser.add_argument(
        "--approved-use",
        required=True,
        choices=(EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY,),
    )
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _validate_distinct_paths(args.source_corpus, args.output)
    source_bytes = args.source_corpus.read_bytes()
    artifact = promote_corpus_artifact(
        source_bytes=source_bytes,
        source_reference=str(args.source_corpus),
        expected_source_sha256=args.expected_source_sha256,
        approved_record_hashes=tuple(args.approved_record_hash),
        review_id=args.review_id,
        review_reference=args.review_reference,
        approved_use=args.approved_use,
        reviewed_by=args.reviewed_by,
        reviewed_at=_parse_timestamp(args.reviewed_at),
    )
    _write_artifact(args.output, artifact)
    review = artifact["human_review"]
    print(
        json.dumps(
            {
                "status": "passed",
                "review_id": review["review_id"],
                "approved_use": review["approved_use"],
                "record_count": len(review["promoted_records"]),
                "training_eligible_count": artifact["training_eligible_count"],
                "artifact_hash": artifact["artifact_hash"],
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return 0


def promote_corpus_artifact(
    *,
    source_bytes: bytes,
    source_reference: str,
    expected_source_sha256: str,
    approved_record_hashes: tuple[str, ...],
    review_id: str,
    review_reference: str,
    approved_use: str,
    reviewed_by: str,
    reviewed_at: datetime,
) -> dict[str, object]:
    _require_nonempty("source_reference", source_reference)
    _require_nonempty("review_id", review_id)
    _require_nonempty("review_reference", review_reference)
    _require_nonempty("reviewed_by", reviewed_by)
    if approved_use != EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY:
        raise ValueError(f"unsupported corpus approval scope: {approved_use}")
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")

    actual_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if expected_source_sha256 != actual_source_sha256:
        raise ValueError(
            "source corpus SHA-256 mismatch: "
            f"expected {expected_source_sha256}, got {actual_source_sha256}"
        )

    source = _load_source_artifact(source_bytes)
    source_bundle = SyntheticCorpusBundle.model_validate(source.get("bundle"))
    _validate_approval_set(
        source_bundle=source_bundle,
        approved_record_hashes=approved_record_hashes,
    )

    reviewed_at_utc = reviewed_at.astimezone(UTC)
    promoted_records = []
    promoted_audit = []
    promoted_receipts = []
    for record in source_bundle.records:
        source_record_hash = record.record_hash
        human_review_ref = (
            f"{review_reference}::review_id={review_id}"
            f"::approved_use={approved_use}"
            f"::source_record_sha256={source_record_hash}"
        )
        promoted = promote_training_record(
            record,
            human_review_ref=human_review_ref,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at_utc,
        )
        verification_id = f"verify-reviewed:{review_id}:{record.record_id}"
        receipt = verify_training_record(
            promoted,
            verification_id=verification_id,
            verifier_id=PROMOTION_VERIFIER_ID,
            verified_at=reviewed_at_utc,
        )
        if not receipt.accepted:
            raise ValueError(f"promoted record failed verification: {record.record_id}")
        promoted_records.append(promoted)
        promoted_receipts.append(receipt)
        promoted_audit.append(
            {
                "record_id": record.record_id,
                "source_record_hash": source_record_hash,
                "promoted_record_hash": promoted.record_hash,
                "verification_id": verification_id,
            }
        )

    promoted_bundle = SyntheticCorpusBundle(
        generator_id=source_bundle.generator_id,
        generated_at=source_bundle.generated_at,
        records=tuple(promoted_records),
        verification_receipts=tuple(promoted_receipts),
    )
    artifact: dict[str, object] = {
        "schema_version": "scout.synthetic_corpus_artifact.v0",
        "generated_at": reviewed_at_utc.isoformat(),
        "source_workspace_benchmark": source["source_workspace_benchmark"],
        "source_workspace_benchmark_sha256": source[
            "source_workspace_benchmark_sha256"
        ],
        "source_workspace_benchmark_role": source[
            "source_workspace_benchmark_role"
        ],
        "source_training_corpus": source_reference,
        "source_training_corpus_sha256": actual_source_sha256,
        "bundle": promoted_bundle.model_dump(mode="json"),
        "training_eligible_count": len(promoted_records),
        "human_review": {
            "schema_version": "scout.synthetic_corpus_human_review.v0",
            "review_id": review_id,
            "review_reference": review_reference,
            "approved_use": approved_use,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at_utc.isoformat(),
            "approved_record_hashes": list(approved_record_hashes),
            "promoted_records": promoted_audit,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    artifact["artifact_hash"] = _canonical_hash(artifact)
    return artifact


def _load_source_artifact(source_bytes: bytes) -> dict[str, Any]:
    payload = json.loads(source_bytes)
    if not isinstance(payload, dict):
        raise ValueError("source corpus must be a JSON object")
    if payload.get("schema_version") != "scout.synthetic_corpus_artifact.v0":
        raise ValueError("unsupported source corpus schema")
    if payload.get("candidate_only") is not True:
        raise ValueError("source corpus must remain candidate-only")
    if payload.get("runtime_safety_truth") is not False:
        raise ValueError("source corpus cannot be runtime safety truth")
    declared_hash = payload.get("artifact_hash")
    hash_payload = dict(payload)
    hash_payload.pop("artifact_hash", None)
    if declared_hash != _canonical_hash(hash_payload):
        raise ValueError("source corpus artifact hash is invalid")

    bundle = SyntheticCorpusBundle.model_validate(payload.get("bundle"))
    eligible_count = sum(
        record.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
        for record in bundle.records
    )
    if payload.get("training_eligible_count") != eligible_count:
        raise ValueError("source corpus training eligible count is inconsistent")
    for field in (
        "source_workspace_benchmark",
        "source_workspace_benchmark_sha256",
        "source_workspace_benchmark_role",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"source corpus {field} is invalid")
    return payload


def _validate_approval_set(
    *,
    source_bundle: SyntheticCorpusBundle,
    approved_record_hashes: tuple[str, ...],
) -> None:
    if len(approved_record_hashes) != len(set(approved_record_hashes)):
        raise ValueError("approved record hashes must be unique")
    if any(not _is_sha256(value) for value in approved_record_hashes):
        raise ValueError("approved record hashes must be lowercase SHA-256 values")
    source_hashes = {record.record_hash for record in source_bundle.records}
    approved_hash_set = set(approved_record_hashes)
    if approved_hash_set != source_hashes:
        missing = sorted(source_hashes - approved_hash_set)
        unexpected = sorted(approved_hash_set - source_hashes)
        raise ValueError(
            "approved record hashes must exactly match the source corpus; "
            f"missing={missing}, unexpected={unexpected}"
        )
    noneligible = [
        record.record_id
        for record in source_bundle.records
        if record.promotion_state
        is not CorpusPromotionState.DETERMINISTICALLY_VERIFIED
    ]
    if noneligible:
        raise ValueError(
            "source corpus contains records that cannot be promoted: "
            f"{sorted(noneligible)}"
        )


def _write_artifact(path: Path, artifact: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _validate_distinct_paths(source_path: Path, output_path: Path) -> None:
    if source_path.resolve() == output_path.resolve():
        raise ValueError("promotion output must not overwrite the source corpus")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--reviewed-at must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _require_nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


if __name__ == "__main__":
    raise SystemExit(main())
