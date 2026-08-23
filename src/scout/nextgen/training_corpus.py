"""Typed, leakage-aware corpus contracts for Scout Workspace experiments."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationInfo, model_validator
from pydantic_core import to_jsonable_python

from scout.nextgen.workspace_snapshot import (
    ScoutWorkspaceSnapshot,
    WorkspaceAnswerBehavior,
    WorkspaceBenchmarkCase,
    WorkspaceDomain,
    WorkspaceSnapshotMode,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

FORBIDDEN_CORPUS_CAPABILITIES = frozenset(
    {
        "mission.write",
        "baseline.write",
        "permission.write",
        "safety.write",
        "emergency.execute",
        "notification.send",
        "device.control",
    }
)


class CorpusSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    FROZEN_GOLD_TEST = "frozen_gold_test"
    ADVERSARIAL_TEST = "adversarial_test"
    LIVE_WORKSPACE_TEST = "live_workspace_test"


class CorpusSource(StrEnum):
    CONTROLLED_SYNTHETIC = "controlled_synthetic"
    REAL_WORKSPACE = "real_workspace"
    TEACHER_GENERATED = "teacher_generated"
    COUNTERFACTUAL = "counterfactual"
    QUALIFICATION_FAILURE = "qualification_failure"
    EXPERT_GOLD = "expert_gold"


class CorpusPromotionState(StrEnum):
    CANDIDATE = "candidate"
    DETERMINISTICALLY_VERIFIED = "deterministically_verified"
    TRAINING_ELIGIBLE = "training_eligible"


class CorpusUse(StrEnum):
    TRAINING = "training"
    PROMPT_GENERATION = "prompt_generation"
    FEW_SHOT = "few_shot"
    SYNTHETIC_SEED = "synthetic_seed"
    EVALUATION = "evaluation"


class CorpusUsageViolation(RuntimeError):
    pass


class CorpusExpectedToolCall(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    tool_name: NonEmptyStr
    arguments: dict[str, Any] = Field(default_factory=dict)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class CorpusAuthorityConstraints(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output_authority: Literal["candidate"] = "candidate"
    may_mutate_authoritative_state: Literal[False] = False
    may_send_notification: Literal[False] = False
    may_execute_emergency_action: Literal[False] = False
    denied_capabilities: tuple[NonEmptyStr, ...] = tuple(
        sorted(FORBIDDEN_CORPUS_CAPABILITIES)
    )
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_denied_capabilities(self) -> "CorpusAuthorityConstraints":
        if len(self.denied_capabilities) != len(set(self.denied_capabilities)):
            raise ValueError("corpus denied capabilities must be unique")
        if not FORBIDDEN_CORPUS_CAPABILITIES.issubset(self.denied_capabilities):
            raise ValueError("corpus authority constraints omit a required denial")
        return self


class CorpusEvidenceRequirement(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: WorkspaceDomain
    source_refs: tuple[NonEmptyStr, ...] = ()
    required: bool = True
    freshness_required: bool = True
    preserve_conflict: bool = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class CorpusExpectedResponse(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    behavior: WorkspaceAnswerBehavior
    required_evidence_refs: tuple[NonEmptyStr, ...] = ()
    missing_domains: tuple[WorkspaceDomain, ...] = ()
    stale_domains: tuple[WorkspaceDomain, ...] = ()
    conflicted_domains: tuple[WorkspaceDomain, ...] = ()
    must_preserve_unknown: bool = False
    must_request_refresh: bool = False
    must_preserve_conflict: bool = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_behavior_flags(self) -> "CorpusExpectedResponse":
        expected_unknown = (
            self.behavior is WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED
        )
        expected_refresh = self.behavior is WorkspaceAnswerBehavior.REFRESH_REQUIRED
        expected_conflict = (
            self.behavior is WorkspaceAnswerBehavior.PRESERVE_CONFLICT
        )
        if self.must_preserve_unknown != expected_unknown:
            raise ValueError("corpus unknown behavior flag is inconsistent")
        if self.must_request_refresh != expected_refresh:
            raise ValueError("corpus refresh behavior flag is inconsistent")
        if self.must_preserve_conflict != expected_conflict:
            raise ValueError("corpus conflict behavior flag is inconsistent")
        return self


class CorpusGeneratorProvenance(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator_id: NonEmptyStr
    generator_version: NonEmptyStr
    generated_at: datetime
    source_case_id: NonEmptyStr
    source_snapshot_hash: NonEmptyStr
    synthetic_evidence: bool
    teacher_model_id: NonEmptyStr | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ScoutTrainingCorpusRecord(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_training_record.v0"] = (
        "scout.workspace_training_record.v0"
    )
    record_id: NonEmptyStr
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: CorpusSource
    split: CorpusSplit
    promotion_state: CorpusPromotionState
    workspace_snapshot: ScoutWorkspaceSnapshot
    user_query: NonEmptyStr
    available_tools: tuple[NonEmptyStr, ...]
    expected_tool_trace: tuple[CorpusExpectedToolCall, ...] = ()
    expected_response: CorpusExpectedResponse
    authority_constraints: CorpusAuthorityConstraints = Field(
        default_factory=CorpusAuthorityConstraints
    )
    evidence_requirements: tuple[CorpusEvidenceRequirement, ...] = ()
    labels: tuple[NonEmptyStr, ...]
    generator_provenance: CorpusGeneratorProvenance
    deterministic_verifier_refs: tuple[NonEmptyStr, ...] = ()
    human_review_ref: NonEmptyStr | None = None
    reviewed_by: NonEmptyStr | None = None
    reviewed_at: datetime | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_record(
        self,
        info: ValidationInfo,
    ) -> "ScoutTrainingCorpusRecord":
        skip_hash_validation = bool(
            info.context and info.context.get("skip_record_hash_validation")
        )
        if self.user_query != self.workspace_snapshot.question:
            raise ValueError("corpus query must match its workspace snapshot")
        if len(self.available_tools) != len(set(self.available_tools)):
            raise ValueError("corpus available tools must be unique")
        if self.labels != tuple(sorted(set(self.labels))):
            raise ValueError("corpus labels must be sorted and unique")
        if FORBIDDEN_CORPUS_CAPABILITIES.intersection(self.available_tools):
            raise ValueError("corpus available tools contain a forbidden capability")
        tools_called = tuple(call.tool_name for call in self.expected_tool_trace)
        if not set(tools_called).issubset(self.available_tools):
            raise ValueError("corpus tool trace is outside the available toolset")
        if tuple(call.sequence for call in self.expected_tool_trace) != tuple(
            range(1, len(self.expected_tool_trace) + 1)
        ):
            raise ValueError("corpus tool trace sequence must be contiguous")
        if self.expected_response.behavior is not (
            self.workspace_snapshot.sufficiency.behavior
        ):
            raise ValueError("corpus response behavior differs from the snapshot")
        if not set(self.expected_response.required_evidence_refs).issubset(
            self.workspace_snapshot.evidence_refs
        ):
            raise ValueError("corpus response requires evidence outside the snapshot")
        sufficiency = self.workspace_snapshot.sufficiency
        if self.expected_response.missing_domains != sufficiency.missing_domains:
            raise ValueError("corpus missing domains differ from the snapshot")
        if self.expected_response.stale_domains != sufficiency.stale_domains:
            raise ValueError("corpus stale domains differ from the snapshot")
        if self.expected_response.conflicted_domains != (
            sufficiency.conflicted_domains
        ):
            raise ValueError("corpus conflict domains differ from the snapshot")
        if self.source is CorpusSource.CONTROLLED_SYNTHETIC:
            if not self.generator_provenance.synthetic_evidence:
                raise ValueError("controlled synthetic corpus must be labeled synthetic")
            if "synthetic" not in self.labels:
                raise ValueError("controlled synthetic corpus requires a label")
            if self.generator_provenance.teacher_model_id is not None:
                raise ValueError("controlled deterministic corpus cannot name a teacher")
        if self.source is CorpusSource.TEACHER_GENERATED:
            if self.generator_provenance.teacher_model_id is None:
                raise ValueError("teacher-generated corpus requires model provenance")
        if self.promotion_state in {
            CorpusPromotionState.DETERMINISTICALLY_VERIFIED,
            CorpusPromotionState.TRAINING_ELIGIBLE,
        } and not self.deterministic_verifier_refs:
            raise ValueError("verified corpus requires deterministic verifier refs")
        if self.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE:
            if not all(
                (self.human_review_ref, self.reviewed_by, self.reviewed_at)
            ):
                raise ValueError("training eligible corpus requires human review")
        if not skip_hash_validation and self.record_hash != training_record_hash(self):
            raise ValueError("corpus record hash does not match its contents")
        return self


class CorpusVerificationCheck(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: NonEmptyStr
    passed: bool
    summary: NonEmptyStr


class CorpusVerificationReceipt(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.corpus_verification_receipt.v0"] = (
        "scout.corpus_verification_receipt.v0"
    )
    verification_id: NonEmptyStr
    record_id: NonEmptyStr
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verifier_id: NonEmptyStr
    verified_at: datetime
    checks: tuple[CorpusVerificationCheck, ...]
    accepted: bool
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_receipt(self) -> "CorpusVerificationReceipt":
        if not self.checks:
            raise ValueError("corpus verification requires checks")
        if self.accepted != all(check.passed for check in self.checks):
            raise ValueError("corpus verification disposition is inconsistent")
        return self


class SyntheticCorpusBundle(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.synthetic_corpus_bundle.v0"] = (
        "scout.synthetic_corpus_bundle.v0"
    )
    generator_id: NonEmptyStr
    generated_at: datetime
    records: tuple[ScoutTrainingCorpusRecord, ...]
    verification_receipts: tuple[CorpusVerificationReceipt, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_bundle(self) -> "SyntheticCorpusBundle":
        if len(self.records) != len(self.verification_receipts):
            raise ValueError("synthetic records require one verification receipt each")
        receipts = {receipt.record_id: receipt for receipt in self.verification_receipts}
        for record in self.records:
            receipt = receipts.get(record.record_id)
            if receipt is None or receipt.record_hash != record.record_hash:
                raise ValueError("synthetic verification receipt binding is invalid")
            if not receipt.accepted:
                raise ValueError("synthetic bundle cannot contain a rejected record")
        return self


class CorpusUsagePolicy:
    """Fail closed when evaluation data is requested for model shaping."""

    _evaluation_only_splits = frozenset(
        {
            CorpusSplit.VALIDATION,
            CorpusSplit.FROZEN_GOLD_TEST,
            CorpusSplit.ADVERSARIAL_TEST,
            CorpusSplit.LIVE_WORKSPACE_TEST,
        }
    )

    def authorize(
        self,
        *,
        record: ScoutTrainingCorpusRecord,
        use: CorpusUse,
    ) -> None:
        if record.split in self._evaluation_only_splits:
            if use is not CorpusUse.EVALUATION:
                raise CorpusUsageViolation(
                    f"corpus split {record.split.value} is evaluation-only"
                )
            return
        if use is CorpusUse.EVALUATION:
            return
        if record.split is not CorpusSplit.TRAIN:
            raise CorpusUsageViolation("only train split records may shape a model")
        if record.promotion_state is not CorpusPromotionState.TRAINING_ELIGIBLE:
            raise CorpusUsageViolation("corpus record is not training eligible")


class SyntheticScenarioGenerator:
    """Build five bounded, deterministic Workspace dependency cases."""

    def __init__(
        self,
        *,
        generator_id: str = "scout.synthetic_workspace_generator.v0",
        verifier_id: str = "scout.synthetic_workspace_verifier.v0",
    ) -> None:
        self.generator_id = generator_id
        self.verifier_id = verifier_id

    def generate(
        self,
        *,
        benchmark_cases: tuple[WorkspaceBenchmarkCase, ...],
        generated_at: datetime,
    ) -> SyntheticCorpusBundle:
        records: list[ScoutTrainingCorpusRecord] = []
        receipts: list[CorpusVerificationReceipt] = []
        for case in benchmark_cases:
            verification_id = f"verify:{case.case_id}:deterministic-v0"
            record = _build_synthetic_record(
                case=case,
                generator_id=self.generator_id,
                generated_at=generated_at,
                verification_id=verification_id,
            )
            receipt = verify_training_record(
                record,
                verification_id=verification_id,
                verifier_id=self.verifier_id,
                verified_at=generated_at,
            )
            if not receipt.accepted:
                raise ValueError(
                    f"synthetic record {record.record_id} failed verification"
                )
            records.append(record)
            receipts.append(receipt)
        return SyntheticCorpusBundle(
            generator_id=self.generator_id,
            generated_at=generated_at,
            records=tuple(records),
            verification_receipts=tuple(receipts),
        )


def verify_training_record(
    record: ScoutTrainingCorpusRecord,
    *,
    verification_id: str,
    verifier_id: str,
    verified_at: datetime,
) -> CorpusVerificationReceipt:
    checks = (
        CorpusVerificationCheck(
            check_id="record_hash",
            passed=record.record_hash == training_record_hash(record),
            summary="Record content is bound to its declared hash.",
        ),
        CorpusVerificationCheck(
            check_id="workspace_behavior",
            passed=(
                record.expected_response.behavior
                is record.workspace_snapshot.sufficiency.behavior
            ),
            summary="Expected behavior follows the typed Workspace sufficiency state.",
        ),
        CorpusVerificationCheck(
            check_id="authority_boundary",
            passed=(
                record.candidate_only
                and not record.runtime_safety_truth
                and not record.authority_constraints.may_mutate_authoritative_state
            ),
            summary="Record remains candidate-only and cannot mutate Scout authority.",
        ),
        CorpusVerificationCheck(
            check_id="tool_scope",
            passed=set(
                call.tool_name for call in record.expected_tool_trace
            ).issubset(record.available_tools),
            summary="Expected tool calls remain inside the declared read-only toolset.",
        ),
        CorpusVerificationCheck(
            check_id="synthetic_label",
            passed=(
                record.source is not CorpusSource.CONTROLLED_SYNTHETIC
                or (
                    record.generator_provenance.synthetic_evidence
                    and "synthetic" in record.labels
                )
            ),
            summary="Synthetic evidence is explicitly labeled and traceable.",
        ),
    )
    return CorpusVerificationReceipt(
        verification_id=verification_id,
        record_id=record.record_id,
        record_hash=record.record_hash,
        verifier_id=verifier_id,
        verified_at=verified_at,
        checks=checks,
        accepted=all(check.passed for check in checks),
    )


def promote_training_record(
    record: ScoutTrainingCorpusRecord,
    *,
    human_review_ref: str,
    reviewed_by: str,
    reviewed_at: datetime,
) -> ScoutTrainingCorpusRecord:
    if record.promotion_state is not CorpusPromotionState.DETERMINISTICALLY_VERIFIED:
        raise ValueError("only deterministically verified corpus can be promoted")
    return replace_training_record(
        record,
        promotion_state=CorpusPromotionState.TRAINING_ELIGIBLE,
        human_review_ref=human_review_ref,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )


def replace_training_record(
    record: ScoutTrainingCorpusRecord,
    **updates: Any,
) -> ScoutTrainingCorpusRecord:
    payload = record.model_dump(mode="python")
    payload.update(updates)
    return _seal_training_record(payload)


def training_record_hash(record: ScoutTrainingCorpusRecord) -> str:
    payload = record.model_dump(mode="json")
    payload.pop("record_hash", None)
    return _canonical_hash(payload)


def _build_synthetic_record(
    *,
    case: WorkspaceBenchmarkCase,
    generator_id: str,
    generated_at: datetime,
    verification_id: str,
) -> ScoutTrainingCorpusRecord:
    snapshot = case.snapshot
    response = CorpusExpectedResponse(
        behavior=case.expected_behavior,
        required_evidence_refs=snapshot.evidence_refs,
        missing_domains=snapshot.sufficiency.missing_domains,
        stale_domains=snapshot.sufficiency.stale_domains,
        conflicted_domains=snapshot.sufficiency.conflicted_domains,
        must_preserve_unknown=(
            case.expected_behavior
            is WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED
        ),
        must_request_refresh=(
            case.expected_behavior is WorkspaceAnswerBehavior.REFRESH_REQUIRED
        ),
        must_preserve_conflict=(
            case.expected_behavior is WorkspaceAnswerBehavior.PRESERVE_CONFLICT
        ),
    )
    payload = {
        "schema_version": "scout.workspace_training_record.v0",
        "record_id": f"corpus:{case.case_id}:v0",
        "record_hash": "0" * 64,
        "source": CorpusSource.CONTROLLED_SYNTHETIC,
        "split": CorpusSplit.TRAIN,
        "promotion_state": CorpusPromotionState.DETERMINISTICALLY_VERIFIED,
        "workspace_snapshot": snapshot,
        "user_query": snapshot.question,
        "available_tools": _available_tools(),
        "expected_tool_trace": _expected_tool_trace(snapshot),
        "expected_response": response,
        "authority_constraints": CorpusAuthorityConstraints(),
        "evidence_requirements": tuple(
            CorpusEvidenceRequirement(
                domain=domain,
                source_refs=tuple(
                    fact.evidence_ref
                    for fact in snapshot.facts
                    if fact.domain is domain
                ),
                preserve_conflict=domain
                in snapshot.sufficiency.conflicted_domains,
            )
            for domain in snapshot.required_domains
        ),
        "labels": tuple(
            sorted(
                {
                "synthetic",
                "workspace_dependency",
                "terrain_analysis",
                snapshot.mode.value,
                }
            )
        ),
        "generator_provenance": CorpusGeneratorProvenance(
            generator_id=generator_id,
            generator_version="v0",
            generated_at=generated_at,
            source_case_id=case.case_id,
            source_snapshot_hash=snapshot.snapshot_hash,
            synthetic_evidence=True,
        ),
        "deterministic_verifier_refs": (verification_id,),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return _seal_training_record(payload)


def _available_tools() -> tuple[str, ...]:
    return (
        "workspace.snapshot.read",
        "workspace.evidence.search",
        "workspace.evidence.refresh",
        "workspace.evidence.compare",
    )


def _expected_tool_trace(
    snapshot: ScoutWorkspaceSnapshot,
) -> tuple[CorpusExpectedToolCall, ...]:
    calls = [
        CorpusExpectedToolCall(
            sequence=1,
            tool_name="workspace.snapshot.read",
            arguments={"snapshot_hash": snapshot.snapshot_hash},
        )
    ]
    if snapshot.mode in {
        WorkspaceSnapshotMode.MISSING,
        WorkspaceSnapshotMode.NO_WORKSPACE,
    }:
        calls.append(
            CorpusExpectedToolCall(
                sequence=2,
                tool_name="workspace.evidence.search",
                arguments={
                    "missing_domains": [
                        domain.value
                        for domain in snapshot.sufficiency.missing_domains
                    ]
                },
            )
        )
    elif snapshot.mode is WorkspaceSnapshotMode.STALE:
        calls.append(
            CorpusExpectedToolCall(
                sequence=2,
                tool_name="workspace.evidence.refresh",
                arguments={
                    "stale_domains": [
                        domain.value
                        for domain in snapshot.sufficiency.stale_domains
                    ]
                },
            )
        )
    elif snapshot.mode is WorkspaceSnapshotMode.CONFLICTED:
        calls.append(
            CorpusExpectedToolCall(
                sequence=2,
                tool_name="workspace.evidence.compare",
                arguments={
                    "conflicted_domains": [
                        domain.value
                        for domain in snapshot.sufficiency.conflicted_domains
                    ]
                },
            )
        )
    return tuple(calls)


def _seal_training_record(payload: dict[str, Any]) -> ScoutTrainingCorpusRecord:
    normalized = to_jsonable_python(payload)
    normalized["record_hash"] = "0" * 64
    provisional = ScoutTrainingCorpusRecord.model_validate(
        normalized,
        context={"skip_record_hash_validation": True},
    )
    sealed_payload = provisional.model_dump(mode="json")
    sealed_payload.pop("record_hash", None)
    sealed_payload["record_hash"] = _canonical_hash(sealed_payload)
    return ScoutTrainingCorpusRecord.model_validate(sealed_payload)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CorpusAuthorityConstraints",
    "CorpusEvidenceRequirement",
    "CorpusExpectedResponse",
    "CorpusExpectedToolCall",
    "CorpusGeneratorProvenance",
    "CorpusPromotionState",
    "CorpusSource",
    "CorpusSplit",
    "CorpusUsagePolicy",
    "CorpusUsageViolation",
    "CorpusUse",
    "CorpusVerificationCheck",
    "CorpusVerificationReceipt",
    "FORBIDDEN_CORPUS_CAPABILITIES",
    "ScoutTrainingCorpusRecord",
    "SyntheticCorpusBundle",
    "SyntheticScenarioGenerator",
    "promote_training_record",
    "replace_training_record",
    "training_record_hash",
    "verify_training_record",
]
