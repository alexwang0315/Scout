"""Experimental learned probe for Scout Workspace answer behavior."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, ValidationInfo, model_validator

from scout.nextgen.training_corpus import (
    CorpusUsagePolicy,
    CorpusUse,
    SyntheticCorpusBundle,
)
from scout.nextgen.workspace_snapshot import (
    ScoutWorkspaceSnapshot,
    WorkspaceAnswerBehavior,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY = (
    "experimental_workspace_behavior_training_only"
)
WORKSPACE_BEHAVIOR_FEATURE_NAMES = (
    "available_domain_ratio",
    "missing_domain_ratio",
    "stale_domain_ratio",
    "conflicted_domain_ratio",
    "fact_coverage_ratio",
    "evidence_coverage_ratio",
    "has_candidate_features",
    "has_unknown_provenance",
)
WORKSPACE_BEHAVIOR_LABELS = (
    WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE,
    WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED,
    WorkspaceAnswerBehavior.REFRESH_REQUIRED,
    WorkspaceAnswerBehavior.PRESERVE_CONFLICT,
)


class WorkspaceBehaviorLinearModel(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_behavior_linear_model.v0"] = (
        "scout.workspace_behavior_linear_model.v0"
    )
    training_run_id: NonEmptyStr
    trainer_id: Literal["scout.workspace_behavior_linear_probe.v0"] = (
        "scout.workspace_behavior_linear_probe.v0"
    )
    trained_at: datetime
    source_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_id: NonEmptyStr
    approved_use: Literal["experimental_workspace_behavior_training_only"] = (
        EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY
    )
    training_record_hashes: tuple[str, ...]
    training_record_count: int = Field(ge=1)
    feature_names: tuple[NonEmptyStr, ...]
    class_labels: tuple[WorkspaceAnswerBehavior, ...]
    weights: tuple[tuple[float, ...], ...]
    biases: tuple[float, ...]
    epochs: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    l2_regularization: float = Field(ge=0)
    initial_loss: float = Field(ge=0)
    final_loss: float = Field(ge=0)
    training_accuracy: float = Field(ge=0, le=1)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    production_promotion_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_model(
        self,
        info: ValidationInfo,
    ) -> "WorkspaceBehaviorLinearModel":
        if self.trained_at.tzinfo is None:
            raise ValueError("Workspace behavior training timestamp must be aware")
        if self.feature_names != WORKSPACE_BEHAVIOR_FEATURE_NAMES:
            raise ValueError("Workspace behavior feature contract is invalid")
        if self.class_labels != WORKSPACE_BEHAVIOR_LABELS:
            raise ValueError("Workspace behavior label contract is invalid")
        if self.training_record_count != len(self.training_record_hashes):
            raise ValueError("Workspace behavior training record count is invalid")
        if len(set(self.training_record_hashes)) != len(self.training_record_hashes):
            raise ValueError("Workspace behavior training hashes must be unique")
        if any(not _is_sha256(value) for value in self.training_record_hashes):
            raise ValueError("Workspace behavior training hash is invalid")
        if len(self.weights) != len(self.class_labels):
            raise ValueError("Workspace behavior weight class count is invalid")
        if any(len(row) != len(self.feature_names) for row in self.weights):
            raise ValueError("Workspace behavior weight feature count is invalid")
        if len(self.biases) != len(self.class_labels):
            raise ValueError("Workspace behavior bias count is invalid")
        numeric_values = (
            *self.biases,
            *(value for row in self.weights for value in row),
            self.learning_rate,
            self.l2_regularization,
            self.initial_loss,
            self.final_loss,
            self.training_accuracy,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise ValueError("Workspace behavior model contains non-finite values")
        skip_hash = bool(
            info.context and info.context.get("skip_model_hash_validation")
        )
        if not skip_hash and self.model_hash != workspace_behavior_model_hash(self):
            raise ValueError("Workspace behavior model hash is invalid")
        return self


class WorkspaceBehaviorPrediction(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    behavior: WorkspaceAnswerBehavior
    confidence: float = Field(ge=0, le=1)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def train_workspace_behavior_model(
    *,
    training_run_id: str,
    trained_at: datetime,
    source_corpus_sha256: str,
    source_artifact_hash: str,
    source_review_id: str,
    approved_use: str,
    bundle: SyntheticCorpusBundle,
    epochs: int = 4000,
    learning_rate: float = 0.2,
    l2_regularization: float = 0.001,
) -> WorkspaceBehaviorLinearModel:
    if approved_use != EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY:
        raise ValueError(
            f"unsupported Workspace behavior training scope: {approved_use}"
        )
    if trained_at.tzinfo is None:
        raise ValueError("trained_at must include a timezone")
    if epochs < 1:
        raise ValueError("epochs must be positive")
    if learning_rate <= 0:
        raise ValueError("learning_rate must be positive")
    if l2_regularization < 0:
        raise ValueError("l2_regularization cannot be negative")

    usage_policy = CorpusUsagePolicy()
    records = bundle.records
    if not records:
        raise ValueError("Workspace behavior training requires records")
    for record in records:
        usage_policy.authorize(record=record, use=CorpusUse.TRAINING)
        if approved_use not in str(record.human_review_ref):
            raise ValueError("record human review does not bind the approved use")

    labels_present = {record.expected_response.behavior for record in records}
    if labels_present != set(WORKSPACE_BEHAVIOR_LABELS):
        raise ValueError("Workspace behavior training requires every behavior label")

    inputs = [
        workspace_behavior_features(record.workspace_snapshot) for record in records
    ]
    targets = [
        WORKSPACE_BEHAVIOR_LABELS.index(record.expected_response.behavior)
        for record in records
    ]
    class_count = len(WORKSPACE_BEHAVIOR_LABELS)
    feature_count = len(WORKSPACE_BEHAVIOR_FEATURE_NAMES)
    weights = [[0.0 for _ in range(feature_count)] for _ in range(class_count)]
    biases = [0.0 for _ in range(class_count)]
    initial_loss = _cross_entropy_loss(
        inputs,
        targets,
        weights,
        biases,
        l2_regularization,
    )

    for _ in range(epochs):
        weight_gradient = [
            [0.0 for _ in range(feature_count)] for _ in range(class_count)
        ]
        bias_gradient = [0.0 for _ in range(class_count)]
        for features, target in zip(inputs, targets, strict=True):
            probabilities = _probabilities(features, weights, biases)
            for class_index in range(class_count):
                error = probabilities[class_index] - (
                    1.0 if class_index == target else 0.0
                )
                bias_gradient[class_index] += error
                for feature_index, feature in enumerate(features):
                    weight_gradient[class_index][feature_index] += error * feature
        sample_count = float(len(inputs))
        for class_index in range(class_count):
            biases[class_index] -= (
                learning_rate * bias_gradient[class_index] / sample_count
            )
            for feature_index in range(feature_count):
                regularized_gradient = (
                    weight_gradient[class_index][feature_index] / sample_count
                    + l2_regularization * weights[class_index][feature_index]
                )
                weights[class_index][feature_index] -= (
                    learning_rate * regularized_gradient
                )

    rounded_weights = tuple(tuple(round(value, 12) for value in row) for row in weights)
    rounded_biases = tuple(round(value, 12) for value in biases)
    final_loss = _cross_entropy_loss(
        inputs,
        targets,
        rounded_weights,
        rounded_biases,
        l2_regularization,
    )
    correct = sum(
        _predicted_class(features, rounded_weights, rounded_biases) == target
        for features, target in zip(inputs, targets, strict=True)
    )
    provisional = WorkspaceBehaviorLinearModel.model_construct(
        training_run_id=training_run_id,
        trained_at=trained_at,
        source_corpus_sha256=source_corpus_sha256,
        source_artifact_hash=source_artifact_hash,
        source_review_id=source_review_id,
        approved_use=approved_use,
        training_record_hashes=tuple(record.record_hash for record in records),
        training_record_count=len(records),
        feature_names=WORKSPACE_BEHAVIOR_FEATURE_NAMES,
        class_labels=WORKSPACE_BEHAVIOR_LABELS,
        weights=rounded_weights,
        biases=rounded_biases,
        epochs=epochs,
        learning_rate=learning_rate,
        l2_regularization=l2_regularization,
        initial_loss=initial_loss,
        final_loss=final_loss,
        training_accuracy=correct / len(inputs),
        model_hash="0" * 64,
        candidate_only=True,
        runtime_safety_truth=False,
        production_promotion_allowed=False,
    )
    payload = provisional.model_dump(mode="json")
    payload["model_hash"] = workspace_behavior_model_hash(provisional)
    return WorkspaceBehaviorLinearModel.model_validate(payload)


def predict_workspace_behavior(
    model: WorkspaceBehaviorLinearModel,
    snapshot: ScoutWorkspaceSnapshot,
) -> WorkspaceBehaviorPrediction:
    features = workspace_behavior_features(snapshot)
    probabilities = _probabilities(features, model.weights, model.biases)
    predicted = max(range(len(probabilities)), key=probabilities.__getitem__)
    return WorkspaceBehaviorPrediction(
        behavior=model.class_labels[predicted],
        confidence=probabilities[predicted],
        model_hash=model.model_hash,
    )


def workspace_behavior_features(
    snapshot: ScoutWorkspaceSnapshot,
) -> tuple[float, ...]:
    required_count = max(1, len(snapshot.required_domains))
    sufficiency = snapshot.sufficiency
    fact_count = len(snapshot.facts)
    candidate_feature_count = sum(
        len(fact.candidate_features) for fact in snapshot.facts
    )
    return (
        len(sufficiency.available_domains) / required_count,
        len(sufficiency.missing_domains) / required_count,
        len(sufficiency.stale_domains) / required_count,
        len(sufficiency.conflicted_domains) / required_count,
        min(1.0, fact_count / required_count),
        min(1.0, len(snapshot.evidence_refs) / required_count),
        1.0 if candidate_feature_count else 0.0,
        1.0 if snapshot.unknown_provenance_refs else 0.0,
    )


def workspace_behavior_model_hash(model: WorkspaceBehaviorLinearModel) -> str:
    payload = model.model_dump(mode="json")
    payload.pop("model_hash", None)
    return _canonical_hash(payload)


def _cross_entropy_loss(
    inputs: list[tuple[float, ...]],
    targets: list[int],
    weights: tuple[tuple[float, ...], ...] | list[list[float]],
    biases: tuple[float, ...] | list[float],
    l2_regularization: float,
) -> float:
    data_loss = 0.0
    for features, target in zip(inputs, targets, strict=True):
        probability = _probabilities(features, weights, biases)[target]
        data_loss -= math.log(max(probability, 1e-15))
    regularization_loss = (
        0.5 * l2_regularization * sum(value * value for row in weights for value in row)
    )
    return data_loss / len(inputs) + regularization_loss


def _predicted_class(
    features: tuple[float, ...],
    weights: tuple[tuple[float, ...], ...] | list[list[float]],
    biases: tuple[float, ...] | list[float],
) -> int:
    probabilities = _probabilities(features, weights, biases)
    return max(range(len(probabilities)), key=probabilities.__getitem__)


def _probabilities(
    features: tuple[float, ...],
    weights: tuple[tuple[float, ...], ...] | list[list[float]],
    biases: tuple[float, ...] | list[float],
) -> tuple[float, ...]:
    logits = [
        bias + sum(weight * feature for weight, feature in zip(row, features))
        for row, bias in zip(weights, biases, strict=True)
    ]
    maximum = max(logits)
    exponents = [math.exp(value - maximum) for value in logits]
    total = sum(exponents)
    return tuple(value / total for value in exponents)


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


__all__ = [
    "EXPERIMENTAL_WORKSPACE_BEHAVIOR_TRAINING_ONLY",
    "WORKSPACE_BEHAVIOR_FEATURE_NAMES",
    "WORKSPACE_BEHAVIOR_LABELS",
    "WorkspaceBehaviorLinearModel",
    "WorkspaceBehaviorPrediction",
    "predict_workspace_behavior",
    "train_workspace_behavior_model",
    "workspace_behavior_features",
    "workspace_behavior_model_hash",
]
