from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scout.nextgen.training_corpus import (
    CorpusPromotionState,
    SyntheticCorpusBundle,
)
from tools.scout_ai_promote_training_corpus import (
    EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY,
    _validate_distinct_paths,
    promote_corpus_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "tests/fixtures/nextgen/workspace-training"
    / "synthetic-training-corpus.json"
)
SOURCE_SHA256 = "c0eccf64c5012c0f53d0401919459cf0568b82cbb747d11a8b8ebdb750ee1f3f"
APPROVED_RECORD_HASHES = (
    "355b94c7533f773ca473e0cbefef12bb6b4352d64b2bb43e7b908d9f62a54f0d",
    "cbf642ec6bba0cb0d57535d763714e6303f2c4f1c7b525d99a99126d7807aada",
    "4db23dc7175298d1551f07a2d2e2416a8a39be450eb63490776b4de43ed9a682",
    "26271886f4af996976148d453cf39ab2f43caa9f53843c1c6b2a3e3715efef84",
    "2c1f9f91d25d4b92802d31142a7bd87c37846e0ebe85f0ae6b36ff6b51a37b77",
)
REVIEWED_AT = datetime(2026, 9, 2, 7, 30, tzinfo=UTC)


def _promote(
    *,
    source_sha256: str = SOURCE_SHA256,
    approved_hashes: tuple[str, ...] = APPROVED_RECORD_HASHES,
    approved_use: str = EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY,
) -> dict[str, object]:
    return promote_corpus_artifact(
        source_bytes=SOURCE.read_bytes(),
        source_reference=str(SOURCE.relative_to(ROOT)),
        expected_source_sha256=source_sha256,
        approved_record_hashes=approved_hashes,
        review_id="SCOUT-AI-WORKSPACE-CORPUS-REVIEW-20260902",
        review_reference=(
            "docs/evals/scout-ai-synthetic-corpus-human-review-20260902.md"
        ),
        approved_use=approved_use,
        reviewed_by="alexwang0315",
        reviewed_at=REVIEWED_AT,
    )


def test_exact_hash_approval_promotes_and_reverifies_every_record() -> None:
    artifact = _promote()
    bundle = SyntheticCorpusBundle.model_validate(artifact["bundle"])
    review = artifact["human_review"]

    assert artifact["candidate_only"] is True
    assert artifact["runtime_safety_truth"] is False
    assert artifact["training_eligible_count"] == 5
    assert artifact["source_training_corpus_sha256"] == SOURCE_SHA256
    assert review["approved_use"] == EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY
    assert set(review["approved_record_hashes"]) == set(APPROVED_RECORD_HASHES)
    assert all(
        record.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
        for record in bundle.records
    )
    assert all(record.reviewed_by == "alexwang0315" for record in bundle.records)
    assert all(record.reviewed_at == REVIEWED_AT for record in bundle.records)
    assert all(receipt.accepted for receipt in bundle.verification_receipts)

    promoted = review["promoted_records"]
    promoted_by_id = {item["record_id"]: item for item in promoted}
    assert set(promoted_by_id) == {record.record_id for record in bundle.records}
    assert {
        item["source_record_hash"] for item in promoted
    } == set(APPROVED_RECORD_HASHES)
    assert all(
        promoted_by_id[record.record_id]["promoted_record_hash"]
        == record.record_hash
        for record in bundle.records
    )
    assert all(
        receipt.record_hash
        == promoted_by_id[receipt.record_id]["promoted_record_hash"]
        for receipt in bundle.verification_receipts
    )
    assert all(
        promoted_by_id[record.record_id]["source_record_hash"]
        in record.human_review_ref
        for record in bundle.records
    )


def test_promotion_rejects_a_source_file_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="source corpus SHA-256 mismatch"):
        _promote(source_sha256="0" * 64)


def test_promotion_requires_exact_record_hash_set() -> None:
    with pytest.raises(ValueError, match="approved record hashes must exactly match"):
        _promote(approved_hashes=APPROVED_RECORD_HASHES[:-1])


def test_promotion_rejects_duplicate_record_hashes() -> None:
    with pytest.raises(ValueError, match="approved record hashes must be unique"):
        _promote(
            approved_hashes=APPROVED_RECORD_HASHES + (APPROVED_RECORD_HASHES[0],)
        )


def test_promotion_rejects_any_broader_training_use() -> None:
    with pytest.raises(ValueError, match="unsupported corpus approval scope"):
        _promote(approved_use="production_training")


def test_source_fixture_remains_bound_to_the_reviewed_hash() -> None:
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256


def test_promotion_output_cannot_overwrite_the_source_corpus() -> None:
    with pytest.raises(ValueError, match="must not overwrite the source corpus"):
        _validate_distinct_paths(SOURCE, SOURCE)
