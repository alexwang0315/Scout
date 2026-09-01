"""Fail-closed promotion gate for experimental Scout Workspace training."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from scout.nextgen.training_corpus import (
    CorpusPromotionState,
    CorpusSplit,
    SyntheticCorpusBundle,
)
from scout.nextgen.workspace_model_benchmark import (
    WorkspaceModelBenchmarkDisposition,
    WorkspaceModelBenchmarkReport,
)
from scout.nextgen.workspace_snapshot import (
    ScoutWorkspaceSnapshot,
    WorkspaceBenchmarkArtifactRole,
    WorkspaceBenchmarkCase,
    WorkspaceSnapshotMode,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class WorkspaceTrainingGateCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class WorkspaceTrainingGateDisposition(StrEnum):
    READY_FOR_EXPERIMENTAL_TRAINING = "ready_for_experimental_training"
    BLOCKED_HUMAN_REVIEW = "blocked_human_review"
    BLOCKED_MODEL_QUALITY = "blocked_model_quality"
    REJECTED_EVALUATION_LEAKAGE = "rejected_evaluation_leakage"
    REJECTED_INVALID_EVIDENCE = "rejected_invalid_evidence"


class WorkspaceTrainingGateCheck(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: NonEmptyStr
    status: WorkspaceTrainingGateCheckStatus
    summary: NonEmptyStr


class WorkspaceTrainingGateReport(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_training_gate.v0"] = (
        "scout.workspace_training_gate.v0"
    )
    gate_id: NonEmptyStr
    generated_at: datetime
    frozen_benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_runtime_id: NonEmptyStr
    model_id: NonEmptyStr
    training_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_source_benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_source_benchmark_role: NonEmptyStr
    training_record_count: int = Field(ge=0)
    training_eligible_count: int = Field(ge=0)
    checks: tuple[WorkspaceTrainingGateCheck, ...]
    failed_check_ids: tuple[NonEmptyStr, ...]
    disposition: WorkspaceTrainingGateDisposition
    ready_for_experimental_training: bool
    production_promotion_allowed: Literal[False] = False
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_report(self) -> "WorkspaceTrainingGateReport":
        expected_failed = tuple(
            check.check_id
            for check in self.checks
            if check.status is WorkspaceTrainingGateCheckStatus.FAILED
        )
        if self.failed_check_ids != expected_failed:
            raise ValueError("Workspace training failed checks are inconsistent")
        expected_ready = (
            self.disposition
            is WorkspaceTrainingGateDisposition.READY_FOR_EXPERIMENTAL_TRAINING
        )
        if self.ready_for_experimental_training != expected_ready:
            raise ValueError("Workspace training readiness is inconsistent")
        if self.training_eligible_count > self.training_record_count:
            raise ValueError("Workspace training eligible count is invalid")
        if self.report_hash != workspace_training_gate_report_hash(self):
            raise ValueError("Workspace training gate report hash is invalid")
        return self


def evaluate_workspace_training_gate(
    *,
    generated_at: datetime,
    frozen_benchmark_sha256: str,
    frozen_cases: tuple[WorkspaceBenchmarkCase, ...],
    model_report: WorkspaceModelBenchmarkReport,
    training_artifact_sha256: str,
    training_source_benchmark_sha256: str,
    training_bundle: SyntheticCorpusBundle,
    training_source_benchmark_role: str = (
        WorkspaceBenchmarkArtifactRole.SYNTHETIC_SEED.value
    ),
    gate_id: str = "SCOUT-WORKSPACE-TRAINING-GATE-V0",
) -> WorkspaceTrainingGateReport:
    if not frozen_cases:
        raise ValueError("Workspace training gate requires frozen benchmark cases")

    records = training_bundle.records
    receipts = training_bundle.verification_receipts
    frozen_case_ids = frozenset(case.case_id for case in frozen_cases)
    frozen_snapshot_hashes = frozenset(
        case.snapshot.snapshot_hash for case in frozen_cases
    )
    frozen_semantics = frozenset(
        workspace_case_semantic_fingerprint(case.snapshot) for case in frozen_cases
    )
    training_case_ids = frozenset(
        record.generator_provenance.source_case_id for record in records
    )
    training_snapshot_hashes = frozenset(
        record.generator_provenance.source_snapshot_hash for record in records
    )
    training_semantics = frozenset(
        workspace_case_semantic_fingerprint(record.workspace_snapshot)
        for record in records
    )

    checks = (
        _check(
            "authority_boundary",
            model_report.candidate_only
            and not model_report.runtime_safety_truth
            and training_bundle.candidate_only
            and not training_bundle.runtime_safety_truth
            and all(
                case.candidate_only and not case.runtime_safety_truth
                for case in frozen_cases
            )
            and all(
                record.candidate_only and not record.runtime_safety_truth
                for record in records
            ),
            "Frozen, model, and corpus evidence remain candidate-only.",
        ),
        _check(
            "frozen_benchmark_binding",
            model_report.workspace_benchmark_sha256 == frozen_benchmark_sha256,
            "The model report is hash-bound to the frozen benchmark artifact.",
        ),
        _check(
            "frozen_mode_coverage",
            len(frozen_cases) == len(WorkspaceSnapshotMode)
            and {case.mode for case in frozen_cases} == set(WorkspaceSnapshotMode),
            "Frozen evaluation covers each Workspace dependency mode exactly once.",
        ),
        _check(
            "source_role_is_synthetic_seed",
            training_source_benchmark_role
            == WorkspaceBenchmarkArtifactRole.SYNTHETIC_SEED.value,
            "Training candidates originate from an explicit synthetic-seed artifact.",
        ),
        _check(
            "source_lineage_disjoint",
            training_source_benchmark_sha256 != frozen_benchmark_sha256,
            "Training candidates do not originate from the frozen benchmark artifact.",
        ),
        _check(
            "case_lineage_disjoint",
            frozen_case_ids.isdisjoint(training_case_ids),
            "Training source case IDs do not overlap frozen evaluation case IDs.",
        ),
        _check(
            "snapshot_lineage_disjoint",
            frozen_snapshot_hashes.isdisjoint(training_snapshot_hashes),
            "Training source snapshot hashes do not overlap frozen evaluation snapshots.",
        ),
        _check(
            "semantic_lineage_disjoint",
            frozen_semantics.isdisjoint(training_semantics),
            "Training snapshots are not renamed semantic copies of frozen cases.",
        ),
        _check(
            "model_baseline_quality",
            model_report.disposition is WorkspaceModelBenchmarkDisposition.PASSED
            and model_report.metrics.total_cases == len(frozen_cases)
            and model_report.metrics.passed_cases == len(frozen_cases)
            and model_report.metrics.structured_output_valid_cases == len(frozen_cases)
            and model_report.metrics.workspace_dependency_score == 1.0,
            "A strong model passes every frozen Workspace dependency case.",
        ),
        _check(
            "corpus_verification",
            bool(records)
            and len(records) == len(receipts)
            and all(receipt.accepted for receipt in receipts),
            "Every training candidate has an accepted hash-bound verifier receipt.",
        ),
        _check(
            "training_split_only",
            bool(records)
            and all(record.split is CorpusSplit.TRAIN for record in records),
            "Only TRAIN records are presented to the training gate.",
        ),
        _check(
            "human_review_promotion",
            bool(records)
            and all(
                record.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
                and record.human_review_ref is not None
                and record.reviewed_by is not None
                and record.reviewed_at is not None
                for record in records
            ),
            "Every record has explicit human review and training eligibility.",
        ),
    )
    failed = tuple(
        check.check_id
        for check in checks
        if check.status is WorkspaceTrainingGateCheckStatus.FAILED
    )
    invalid_ids = {
        "authority_boundary",
        "frozen_benchmark_binding",
        "frozen_mode_coverage",
        "corpus_verification",
        "training_split_only",
        "source_role_is_synthetic_seed",
    }
    lineage_ids = {
        "source_lineage_disjoint",
        "case_lineage_disjoint",
        "snapshot_lineage_disjoint",
        "semantic_lineage_disjoint",
    }
    if invalid_ids.intersection(failed):
        disposition = WorkspaceTrainingGateDisposition.REJECTED_INVALID_EVIDENCE
    elif lineage_ids.intersection(failed):
        disposition = WorkspaceTrainingGateDisposition.REJECTED_EVALUATION_LEAKAGE
    elif "model_baseline_quality" in failed:
        disposition = WorkspaceTrainingGateDisposition.BLOCKED_MODEL_QUALITY
    elif "human_review_promotion" in failed:
        disposition = WorkspaceTrainingGateDisposition.BLOCKED_HUMAN_REVIEW
    else:
        disposition = WorkspaceTrainingGateDisposition.READY_FOR_EXPERIMENTAL_TRAINING

    provisional = WorkspaceTrainingGateReport.model_construct(
        gate_id=gate_id,
        generated_at=generated_at,
        frozen_benchmark_sha256=frozen_benchmark_sha256,
        model_report_hash=model_report.report_hash,
        model_runtime_id=model_report.runtime_id,
        model_id=model_report.model_id,
        training_artifact_sha256=training_artifact_sha256,
        training_source_benchmark_sha256=training_source_benchmark_sha256,
        training_source_benchmark_role=training_source_benchmark_role,
        training_record_count=len(records),
        training_eligible_count=sum(
            record.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
            for record in records
        ),
        checks=checks,
        failed_check_ids=failed,
        disposition=disposition,
        ready_for_experimental_training=(
            disposition
            is WorkspaceTrainingGateDisposition.READY_FOR_EXPERIMENTAL_TRAINING
        ),
        production_promotion_allowed=False,
        report_hash="0" * 64,
        candidate_only=True,
        runtime_safety_truth=False,
    )
    payload = provisional.model_dump(mode="json")
    payload.pop("report_hash", None)
    payload["report_hash"] = _canonical_hash(payload)
    return WorkspaceTrainingGateReport.model_validate(payload)


def run_workspace_training_gate(
    *,
    frozen_benchmark_path: Path,
    model_report_path: Path,
    training_corpus_path: Path,
    generated_at: datetime,
) -> WorkspaceTrainingGateReport:
    frozen_bytes = frozen_benchmark_path.read_bytes()
    frozen_payload = _load_hashed_artifact(
        frozen_bytes,
        schema_version="scout.workspace_snapshot_benchmark.v0",
        artifact_name="Workspace benchmark",
    )
    if (
        frozen_payload.get("artifact_role")
        != WorkspaceBenchmarkArtifactRole.MODEL_EVALUATION.value
    ):
        raise ValueError("Workspace benchmark is not model-evaluation data")
    raw_cases = frozen_payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("Workspace benchmark cases are missing")
    frozen_cases = tuple(
        WorkspaceBenchmarkCase.model_validate(case) for case in raw_cases
    )

    model_report = WorkspaceModelBenchmarkReport.model_validate_json(
        model_report_path.read_bytes()
    )

    training_bytes = training_corpus_path.read_bytes()
    training_payload = _load_hashed_artifact(
        training_bytes,
        schema_version="scout.synthetic_corpus_artifact.v0",
        artifact_name="Synthetic corpus",
    )
    source_hash = training_payload.get("source_workspace_benchmark_sha256")
    if not isinstance(source_hash, str) or not _is_sha256(source_hash):
        raise ValueError("Synthetic corpus source benchmark hash is invalid")
    source_role = training_payload.get("source_workspace_benchmark_role")
    if not isinstance(source_role, str) or not source_role.strip():
        source_role = "unknown"
    training_bundle = SyntheticCorpusBundle.model_validate(
        training_payload.get("bundle")
    )
    declared_training_eligible = training_payload.get("training_eligible_count")
    actual_training_eligible = sum(
        record.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
        for record in training_bundle.records
    )
    if declared_training_eligible != actual_training_eligible:
        raise ValueError("Synthetic corpus training eligible count is inconsistent")

    return evaluate_workspace_training_gate(
        generated_at=generated_at,
        frozen_benchmark_sha256=hashlib.sha256(frozen_bytes).hexdigest(),
        frozen_cases=frozen_cases,
        model_report=model_report,
        training_artifact_sha256=hashlib.sha256(training_bytes).hexdigest(),
        training_source_benchmark_sha256=source_hash,
        training_source_benchmark_role=source_role,
        training_bundle=training_bundle,
    )


def workspace_case_semantic_fingerprint(snapshot: ScoutWorkspaceSnapshot) -> str:
    payload = {
        "task_type": snapshot.task_type.value,
        "question": snapshot.question,
        "mode": snapshot.mode.value,
        "required_domains": [domain.value for domain in snapshot.required_domains],
        "facts": [
            {
                "domain": fact.domain.value,
                "status": fact.status.value,
                "authority": fact.authority.value,
                "source_type": fact.source_type,
                "summary": fact.summary,
                "method": fact.method,
                "resolution": fact.resolution,
                "candidate_features": [
                    {
                        "kind": feature.kind,
                        "claim": feature.claim,
                        "confidence": feature.confidence,
                    }
                    for feature in fact.candidate_features
                ],
                "conflicts": list(fact.conflict_descriptions),
            }
            for fact in snapshot.facts
        ],
        "sufficiency": {
            "available": [
                domain.value for domain in snapshot.sufficiency.available_domains
            ],
            "missing": [
                domain.value for domain in snapshot.sufficiency.missing_domains
            ],
            "stale": [domain.value for domain in snapshot.sufficiency.stale_domains],
            "conflicted": [
                domain.value for domain in snapshot.sufficiency.conflicted_domains
            ],
            "behavior": snapshot.sufficiency.behavior.value,
        },
    }
    return _canonical_hash(payload)


def workspace_training_gate_report_hash(report: WorkspaceTrainingGateReport) -> str:
    payload = report.model_dump(mode="json")
    payload.pop("report_hash", None)
    return _canonical_hash(payload)


def _check(
    check_id: str,
    passed: bool,
    summary: str,
) -> WorkspaceTrainingGateCheck:
    return WorkspaceTrainingGateCheck(
        check_id=check_id,
        status=(
            WorkspaceTrainingGateCheckStatus.PASSED
            if passed
            else WorkspaceTrainingGateCheckStatus.FAILED
        ),
        summary=summary,
    )


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_hashed_artifact(
    raw: bytes,
    *,
    schema_version: str,
    artifact_name: str,
) -> dict[str, object]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{artifact_name} must be a JSON object")
    if payload.get("schema_version") != schema_version:
        raise ValueError(f"unsupported {artifact_name} schema")
    if payload.get("candidate_only") is not True:
        raise ValueError(f"{artifact_name} must remain candidate-only")
    if payload.get("runtime_safety_truth") is not False:
        raise ValueError(f"{artifact_name} cannot be runtime safety truth")
    declared_hash = payload.get("artifact_hash")
    content = dict(payload)
    content.pop("artifact_hash", None)
    if declared_hash != _canonical_hash(content):
        raise ValueError(f"{artifact_name} artifact hash is invalid")
    return payload


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


__all__ = [
    "WorkspaceTrainingGateCheck",
    "WorkspaceTrainingGateCheckStatus",
    "WorkspaceTrainingGateDisposition",
    "WorkspaceTrainingGateReport",
    "evaluate_workspace_training_gate",
    "run_workspace_training_gate",
    "workspace_case_semantic_fingerprint",
    "workspace_training_gate_report_hash",
]
