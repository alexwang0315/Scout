"""Typed evidence for promoting a read-only Scout Assistant model route."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationInfo, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"
PROMOTION_EVIDENCE_TYPES = frozenset(
    {
        "model_runtime_qualification",
        "workspace_five_mode_benchmark",
        "assistant_route_smoke",
        "assistant_workspace_api_smoke",
    }
)


class AssistantProductionSmokeReport(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.assistant_production_smoke.v0"] = (
        "scout.assistant_production_smoke.v0"
    )
    generated_at: datetime
    disposition: Literal["passed"] = "passed"
    config_path: NonEmptyStr
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    workspace_project_id: NonEmptyStr
    workspace_project_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    model_name: NonEmptyStr
    observed_model_id: NonEmptyStr
    provider_class: Literal["PydanticAIAssistantProvider"]
    http_status: Literal[200]
    answer: NonEmptyStr
    answer_sha256: str = Field(pattern=SHA256_PATTERN)
    answer_chars: int = Field(ge=1)
    cited_source_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    selected_tool_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    executed_tool_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    request_count: int = Field(ge=1, le=10)
    tool_call_count: int = Field(ge=1, le=10)
    deterministic_tool_completion_count: int = Field(ge=0, le=10)
    latency_ms: int = Field(ge=0)
    grounding_passed: Literal[True]
    mser_mode: Literal["enforce"]
    mser_sufficiency_status: Literal["sufficient", "insufficient"]
    mser_reasoning_disposition: Literal[
        "ready_to_reason",
        "ready_to_explain_gap",
    ]
    mser_answer_verification_passed: Literal[True]
    model_profile_used: Literal["cloud"]
    safe_failure: Literal[False]
    budget_stop_reason: None = None
    failover_reason: None = None
    read_only: Literal[True]
    phase1_mutation_allowed: Literal[False]
    safety_mutation_allowed: Literal[False]
    outbound_send_allowed: Literal[False]
    hardware_control_allowed: Literal[False]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    report_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_report(
        self,
        info: ValidationInfo,
    ) -> "AssistantProductionSmokeReport":
        if self.generated_at.tzinfo is None:
            raise ValueError("assistant production smoke timestamp must be aware")
        if self.answer_chars != len(self.answer):
            raise ValueError("assistant production smoke answer length is invalid")
        if self.answer_sha256 != _text_sha256(self.answer):
            raise ValueError("assistant production smoke answer hash is invalid")
        if set(self.selected_tool_ids) != set(self.executed_tool_ids):
            raise ValueError(
                "assistant production smoke did not execute every selected tool"
            )
        if self.tool_call_count != len(self.executed_tool_ids):
            raise ValueError("assistant production smoke tool count is invalid")
        if (
            self.mser_sufficiency_status == "insufficient"
            and self.mser_reasoning_disposition != "ready_to_explain_gap"
        ):
            raise ValueError(
                "insufficient MSER evidence must preserve the evidence gap"
            )
        skip_hash = bool(info.context and info.context.get("skip_hash_validation"))
        if not skip_hash and self.report_hash != assistant_smoke_report_hash(self):
            raise ValueError("assistant production smoke report hash is invalid")
        return self


class PromotionEvidenceRef(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_type: Literal[
        "model_runtime_qualification",
        "workspace_five_mode_benchmark",
        "assistant_route_smoke",
        "assistant_workspace_api_smoke",
    ]
    path: NonEmptyStr
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)


class AssistantModelProductionPromotionManifest(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.assistant_model_promotion.v0"] = (
        "scout.assistant_model_promotion.v0"
    )
    promotion_id: NonEmptyStr
    generated_at: datetime
    scope: Literal["read_only_workspace_assistant"] = "read_only_workspace_assistant"
    promoted_model_name: NonEmptyStr
    observed_model_id: NonEmptyStr
    rollback_model_name: NonEmptyStr
    local_fallback_model_name: NonEmptyStr
    evidence: tuple[PromotionEvidenceRef, ...] = Field(min_length=4, max_length=4)
    model_runtime_qualification_passed: Literal[True]
    workspace_five_mode_benchmark_passed: Literal[True]
    assistant_route_smoke_passed: Literal[True]
    assistant_workspace_api_smoke_passed: Literal[True]
    authority_boundary_passed: Literal[True]
    local_fallback_preserved: Literal[True]
    behavior_probe_promoted: Literal[False] = False
    production_promotion_allowed: Literal[True]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_manifest(
        self,
        info: ValidationInfo,
    ) -> "AssistantModelProductionPromotionManifest":
        if self.generated_at.tzinfo is None:
            raise ValueError("assistant model promotion timestamp must be aware")
        evidence_types = {item.evidence_type for item in self.evidence}
        if evidence_types != PROMOTION_EVIDENCE_TYPES:
            raise ValueError("assistant model promotion evidence set is incomplete")
        skip_hash = bool(info.context and info.context.get("skip_hash_validation"))
        if not skip_hash and self.manifest_hash != promotion_manifest_hash(self):
            raise ValueError("assistant model promotion manifest hash is invalid")
        return self


def assistant_smoke_report_hash(report: AssistantProductionSmokeReport) -> str:
    payload = report.model_dump(mode="json")
    payload.pop("report_hash", None)
    return canonical_hash(payload)


def promotion_manifest_hash(
    manifest: AssistantModelProductionPromotionManifest,
) -> str:
    payload = manifest.model_dump(mode="json")
    payload.pop("manifest_hash", None)
    return canonical_hash(payload)


def load_promotion_manifest(
    path: Path | str,
) -> AssistantModelProductionPromotionManifest:
    return AssistantModelProductionPromotionManifest.model_validate_json(
        Path(path).read_bytes()
    )


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AssistantModelProductionPromotionManifest",
    "AssistantProductionSmokeReport",
    "PromotionEvidenceRef",
    "assistant_smoke_report_hash",
    "canonical_hash",
    "file_sha256",
    "load_promotion_manifest",
    "promotion_manifest_hash",
]
