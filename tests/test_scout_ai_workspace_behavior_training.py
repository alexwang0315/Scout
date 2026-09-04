from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scout.nextgen.training_corpus import SyntheticCorpusBundle
from scout.nextgen.workspace_behavior_model import (
    EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY,
    WorkspaceBehaviorLinearModel,
    predict_workspace_behavior,
    train_workspace_behavior_model,
)
from scout.nextgen.workspace_behavior_qualification import (
    WorkspaceBehaviorQualificationDisposition,
    qualify_workspace_behavior_model,
)
from scout.nextgen.workspace_snapshot import WorkspaceBenchmarkCase
from tools.scout_ai_workspace_behavior_train import load_approved_training_corpus


ROOT = Path(__file__).resolve().parents[1]
TRAINING_CORPUS = (
    ROOT
    / "artifacts/scout-ai-nextgen/workspace-training-gates-20260902"
    / "synthetic-training-corpus-human-reviewed.json"
)
FROZEN_BENCHMARK = (
    ROOT
    / "artifacts/scout-ai-nextgen/workspace-training-gates-20260901"
    / "frozen-workspace-benchmark.json"
)
TRAINED_AT = datetime(2026, 9, 2, 2, 0, tzinfo=UTC)


def _training_payload() -> dict[str, object]:
    return json.loads(TRAINING_CORPUS.read_text(encoding="utf-8"))


def _train() -> WorkspaceBehaviorLinearModel:
    payload = _training_payload()
    return train_workspace_behavior_model(
        training_run_id="SCOUT-AI-WORKSPACE-BEHAVIOR-TRAIN-20260902",
        trained_at=TRAINED_AT,
        source_corpus_sha256=hashlib.sha256(TRAINING_CORPUS.read_bytes()).hexdigest(),
        source_artifact_hash=str(payload["artifact_hash"]),
        source_review_id=str(payload["human_review"]["review_id"]),
        approved_use=str(payload["human_review"]["approved_use"]),
        bundle=SyntheticCorpusBundle.model_validate(payload["bundle"]),
        epochs=4000,
        learning_rate=0.2,
        l2_regularization=0.001,
    )


def test_training_produces_hash_bound_candidate_only_linear_probe() -> None:
    model = _train()

    assert model.training_record_count == 5
    assert model.training_accuracy == 1.0
    assert model.approved_use == EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY
    assert model.candidate_only is True
    assert model.runtime_safety_truth is False
    assert model.production_promotion_allowed is False
    assert model.final_loss < model.initial_loss
    assert len(model.model_hash) == 64

    reparsed = WorkspaceBehaviorLinearModel.model_validate_json(model.model_dump_json())
    assert reparsed == model


def test_trained_probe_fits_every_human_reviewed_training_record() -> None:
    payload = _training_payload()
    bundle = SyntheticCorpusBundle.model_validate(payload["bundle"])
    model = _train()

    predictions = [
        predict_workspace_behavior(model, record.workspace_snapshot)
        for record in bundle.records
    ]

    assert [prediction.behavior for prediction in predictions] == [
        record.expected_response.behavior for record in bundle.records
    ]


def test_trained_probe_generalizes_to_disjoint_frozen_five_mode_cases() -> None:
    frozen_payload = json.loads(FROZEN_BENCHMARK.read_text(encoding="utf-8"))
    cases = tuple(
        WorkspaceBenchmarkCase.model_validate(case) for case in frozen_payload["cases"]
    )
    model = _train()

    predictions = [predict_workspace_behavior(model, case.snapshot) for case in cases]

    assert len(predictions) == 5
    assert [prediction.behavior for prediction in predictions] == [
        case.expected_behavior for case in cases
    ]


def test_training_rejects_any_scope_broader_than_human_approval() -> None:
    payload = _training_payload()
    bundle = SyntheticCorpusBundle.model_validate(payload["bundle"])

    try:
        train_workspace_behavior_model(
            training_run_id="SCOUT-AI-WORKSPACE-BEHAVIOR-TRAIN-20260902",
            trained_at=TRAINED_AT,
            source_corpus_sha256=hashlib.sha256(
                TRAINING_CORPUS.read_bytes()
            ).hexdigest(),
            source_artifact_hash=str(payload["artifact_hash"]),
            source_review_id=str(payload["human_review"]["review_id"]),
            approved_use="production_training",
            bundle=bundle,
        )
    except ValueError as exc:
        assert "unsupported Workspace behavior training scope" in str(exc)
    else:
        raise AssertionError("broader production scope must fail closed")


def test_training_loader_validates_human_review_and_promoted_hash_bindings() -> None:
    payload, bundle = load_approved_training_corpus(
        source_bytes=TRAINING_CORPUS.read_bytes(),
        expected_source_sha256=hashlib.sha256(TRAINING_CORPUS.read_bytes()).hexdigest(),
    )

    assert payload["human_review"]["approved_use"] == (
        EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY
    )
    assert {record.record_hash for record in bundle.records} == {
        item["promoted_record_hash"]
        for item in payload["human_review"]["promoted_records"]
    }


def test_training_loader_rejects_source_sha_mismatch() -> None:
    with pytest.raises(ValueError, match="training corpus SHA-256 mismatch"):
        load_approved_training_corpus(
            source_bytes=TRAINING_CORPUS.read_bytes(),
            expected_source_sha256="0" * 64,
        )


def test_trained_probe_passes_offline_frozen_qualification() -> None:
    frozen_payload = json.loads(FROZEN_BENCHMARK.read_text(encoding="utf-8"))
    cases = tuple(
        WorkspaceBenchmarkCase.model_validate(case) for case in frozen_payload["cases"]
    )
    model = _train()
    model_bytes = (model.model_dump_json(indent=2) + "\n").encode("utf-8")

    report = qualify_workspace_behavior_model(
        model=model,
        model_file_sha256=hashlib.sha256(model_bytes).hexdigest(),
        model_file_bytes=len(model_bytes),
        frozen_benchmark_sha256=hashlib.sha256(
            FROZEN_BENCHMARK.read_bytes()
        ).hexdigest(),
        frozen_cases=cases,
        qualified_at=TRAINED_AT,
    )

    assert report.disposition is WorkspaceBehaviorQualificationDisposition.PASSED
    assert report.passed_cases == 5
    assert report.failed_case_ids == ()
    assert report.offline_execution is True
    assert report.deterministic_authority_remains_primary is True
    assert report.production_promotion_allowed is False
    assert report.peak_tracemalloc_bytes >= 0
