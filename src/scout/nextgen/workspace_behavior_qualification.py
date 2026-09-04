"""Offline qualification for the experimental Workspace behavior probe."""

from __future__ import annotations

import hashlib
import json
import math
import time
import tracemalloc
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, ValidationInfo, model_validator

from scout.nextgen.workspace_behavior_model import (
    WorkspaceBehaviorLinearModel,
    predict_workspace_behavior,
)
from scout.nextgen.workspace_snapshot import (
    WorkspaceAnswerBehavior,
    WorkspaceBenchmarkCase,
    WorkspaceSnapshotMode,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class WorkspaceBehaviorQualificationDisposition(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class WorkspaceBehaviorQualificationCaseResult(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyStr
    mode: WorkspaceSnapshotMode
    expected_behavior: WorkspaceAnswerBehavior
    predicted_behavior: WorkspaceAnswerBehavior
    confidence: float = Field(ge=0, le=1)
    passed: bool
    latency_us: int = Field(ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class WorkspaceBehaviorQualificationReport(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_behavior_qualification.v0"] = (
        "scout.workspace_behavior_qualification.v0"
    )
    qualification_id: Literal["SCOUT-WORKSPACE-BEHAVIOR-QUAL-V0"] = (
        "SCOUT-WORKSPACE-BEHAVIOR-QUAL-V0"
    )
    qualified_at: datetime
    disposition: WorkspaceBehaviorQualificationDisposition
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_file_bytes: int = Field(ge=1)
    source_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_cases: int = Field(ge=1)
    passed_cases: int = Field(ge=0)
    failed_case_ids: tuple[NonEmptyStr, ...]
    case_results: tuple[WorkspaceBehaviorQualificationCaseResult, ...]
    total_latency_us: int = Field(ge=0)
    max_case_latency_us: int = Field(ge=0)
    peak_tracemalloc_bytes: int = Field(ge=0)
    mean_confidence: float = Field(ge=0, le=1)
    offline_execution: Literal[True] = True
    deterministic_authority_remains_primary: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    production_promotion_allowed: Literal[False] = False
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(
        self,
        info: ValidationInfo,
    ) -> "WorkspaceBehaviorQualificationReport":
        if self.qualified_at.tzinfo is None:
            raise ValueError("Workspace behavior qualification timestamp must be aware")
        if self.total_cases != len(self.case_results):
            raise ValueError("Workspace behavior qualification case count is invalid")
        actual_passed = sum(result.passed for result in self.case_results)
        if self.passed_cases != actual_passed:
            raise ValueError("Workspace behavior passed case count is invalid")
        actual_failed = tuple(
            result.case_id for result in self.case_results if not result.passed
        )
        if self.failed_case_ids != actual_failed:
            raise ValueError("Workspace behavior failed case IDs are invalid")
        expected_disposition = (
            WorkspaceBehaviorQualificationDisposition.PASSED
            if self.passed_cases == self.total_cases
            else WorkspaceBehaviorQualificationDisposition.FAILED
        )
        if self.disposition is not expected_disposition:
            raise ValueError("Workspace behavior qualification disposition is invalid")
        if not math.isfinite(self.mean_confidence):
            raise ValueError("Workspace behavior confidence is not finite")
        skip_hash = bool(
            info.context and info.context.get("skip_report_hash_validation")
        )
        if not skip_hash and self.report_hash != workspace_behavior_report_hash(self):
            raise ValueError("Workspace behavior qualification hash is invalid")
        return self


def qualify_workspace_behavior_model(
    *,
    model: WorkspaceBehaviorLinearModel,
    model_file_sha256: str,
    model_file_bytes: int,
    frozen_benchmark_sha256: str,
    frozen_cases: tuple[WorkspaceBenchmarkCase, ...],
    qualified_at: datetime,
) -> WorkspaceBehaviorQualificationReport:
    if qualified_at.tzinfo is None:
        raise ValueError("qualified_at must include a timezone")
    if len(frozen_cases) != len(WorkspaceSnapshotMode) or {
        case.mode for case in frozen_cases
    } != set(WorkspaceSnapshotMode):
        raise ValueError("Workspace behavior qualification requires five frozen modes")
    if any(
        not case.candidate_only or case.runtime_safety_truth for case in frozen_cases
    ):
        raise ValueError("Workspace behavior frozen cases violate authority boundary")

    results: list[WorkspaceBehaviorQualificationCaseResult] = []
    tracemalloc.start()
    total_started = time.perf_counter_ns()
    try:
        for case in frozen_cases:
            started = time.perf_counter_ns()
            prediction = predict_workspace_behavior(model, case.snapshot)
            latency_us = max(0, (time.perf_counter_ns() - started) // 1000)
            results.append(
                WorkspaceBehaviorQualificationCaseResult(
                    case_id=case.case_id,
                    mode=case.mode,
                    expected_behavior=case.expected_behavior,
                    predicted_behavior=prediction.behavior,
                    confidence=prediction.confidence,
                    passed=prediction.behavior is case.expected_behavior,
                    latency_us=latency_us,
                )
            )
        total_latency_us = max(0, (time.perf_counter_ns() - total_started) // 1000)
        _, peak_tracemalloc_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    passed_cases = sum(result.passed for result in results)
    disposition = (
        WorkspaceBehaviorQualificationDisposition.PASSED
        if passed_cases == len(results)
        else WorkspaceBehaviorQualificationDisposition.FAILED
    )
    provisional = WorkspaceBehaviorQualificationReport.model_construct(
        qualified_at=qualified_at,
        disposition=disposition,
        model_hash=model.model_hash,
        model_file_sha256=model_file_sha256,
        model_file_bytes=model_file_bytes,
        source_corpus_sha256=model.source_corpus_sha256,
        frozen_benchmark_sha256=frozen_benchmark_sha256,
        total_cases=len(results),
        passed_cases=passed_cases,
        failed_case_ids=tuple(
            result.case_id for result in results if not result.passed
        ),
        case_results=tuple(results),
        total_latency_us=total_latency_us,
        max_case_latency_us=max(result.latency_us for result in results),
        peak_tracemalloc_bytes=peak_tracemalloc_bytes,
        mean_confidence=sum(result.confidence for result in results) / len(results),
        offline_execution=True,
        deterministic_authority_remains_primary=True,
        candidate_only=True,
        runtime_safety_truth=False,
        production_promotion_allowed=False,
        report_hash="0" * 64,
    )
    payload = provisional.model_dump(mode="json")
    payload["report_hash"] = workspace_behavior_report_hash(provisional)
    return WorkspaceBehaviorQualificationReport.model_validate(payload)


def workspace_behavior_report_hash(
    report: WorkspaceBehaviorQualificationReport,
) -> str:
    payload = report.model_dump(mode="json")
    payload.pop("report_hash", None)
    return _canonical_hash(payload)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "WorkspaceBehaviorQualificationCaseResult",
    "WorkspaceBehaviorQualificationDisposition",
    "WorkspaceBehaviorQualificationReport",
    "qualify_workspace_behavior_model",
    "workspace_behavior_report_hash",
]
