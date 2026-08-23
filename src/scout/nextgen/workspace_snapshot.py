"""Immutable, task-aware Scout Workspace projection for experimental AI paths."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, model_validator

from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceTaskType,
    WorkspaceBinding,
)
from scout.nextgen.praison_service import EvidenceCatalog, EvidenceCatalogItem
from scout.schemas.base import NonEmptyStr, SchemaModel


class WorkspaceSnapshotMode(StrEnum):
    FULL = "full"
    MISSING = "missing"
    STALE = "stale"
    CONFLICTED = "conflicted"
    NO_WORKSPACE = "no_workspace"


class WorkspaceAnswerBehavior(StrEnum):
    ANSWER_WITH_EVIDENCE = "answer_with_evidence"
    MORE_EVIDENCE_REQUIRED = "more_evidence_required"
    REFRESH_REQUIRED = "refresh_required"
    PRESERVE_CONFLICT = "preserve_conflict"


class WorkspaceAuthority(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    REVIEWED = "reviewed"
    OPERATIONAL = "operational"


class WorkspaceDomain(StrEnum):
    ROUTE = "route"
    TERRAIN = "terrain"
    WEATHER = "weather"
    POSITION = "position"
    PACE = "pace"
    PERMISSION = "permission"
    SAFETY = "safety"


class WorkspaceFactStatus(StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    CONFLICTED = "conflicted"


class WorkspaceCandidateFeature(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: NonEmptyStr
    kind: NonEmptyStr
    claim: NonEmptyStr
    confidence: float = Field(ge=0, le=1)
    evidence_id: NonEmptyStr
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class WorkspaceEvidenceFact(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: NonEmptyStr
    domain: WorkspaceDomain
    status: WorkspaceFactStatus
    authority: WorkspaceAuthority
    evidence_id: NonEmptyStr
    evidence_ref: NonEmptyStr
    source_type: NonEmptyStr
    summary: str = Field(max_length=1000)
    content_hash: NonEmptyStr
    generated_at: datetime
    observed_at: datetime | None = None
    age_seconds: int = Field(ge=0)
    method: str | None = None
    resolution: str | None = None
    candidate_features: tuple[WorkspaceCandidateFeature, ...] = ()
    conflict_descriptions: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ContextSufficiencyAssessment(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_domains: tuple[WorkspaceDomain, ...]
    available_domains: tuple[WorkspaceDomain, ...] = ()
    missing_domains: tuple[WorkspaceDomain, ...] = ()
    stale_domains: tuple[WorkspaceDomain, ...] = ()
    conflicted_domains: tuple[WorkspaceDomain, ...] = ()
    missing_evidence_refs: tuple[NonEmptyStr, ...] = ()
    sufficient: bool
    behavior: WorkspaceAnswerBehavior
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_behavior(self) -> "ContextSufficiencyAssessment":
        expected = _expected_behavior(
            has_facts=bool(self.available_domains),
            missing=bool(self.missing_domains),
            stale=bool(self.stale_domains),
            conflicted=bool(self.conflicted_domains),
        )
        if self.behavior is not expected:
            raise ValueError("workspace sufficiency behavior is inconsistent")
        if self.sufficient != (expected is WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE):
            raise ValueError("workspace sufficient flag is inconsistent")
        return self


class ScoutWorkspaceSnapshot(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_snapshot.v0"] = (
        "scout.workspace_snapshot.v0"
    )
    snapshot_id: UUID = Field(default_factory=uuid4)
    snapshot_hash: NonEmptyStr
    compiled_at: datetime
    task_type: IntelligenceTaskType
    question: NonEmptyStr
    workspace_binding: WorkspaceBinding
    mode: WorkspaceSnapshotMode
    required_domains: tuple[WorkspaceDomain, ...]
    facts: tuple[WorkspaceEvidenceFact, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    irrelevant_evidence_refs: tuple[NonEmptyStr, ...] = ()
    unknown_provenance_refs: tuple[NonEmptyStr, ...] = ()
    sufficiency: ContextSufficiencyAssessment
    context_budget_tokens: int = Field(ge=1)
    estimated_tokens: int = Field(ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_snapshot(self) -> "ScoutWorkspaceSnapshot":
        refs = tuple(fact.evidence_ref for fact in self.facts)
        if len(refs) != len(set(refs)):
            raise ValueError("workspace snapshot evidence refs must be unique")
        if refs != self.evidence_refs:
            raise ValueError("workspace snapshot refs must match fact order")
        if self.estimated_tokens > self.context_budget_tokens:
            raise ValueError("workspace snapshot exceeds its context budget")
        if self.required_domains != self.sufficiency.required_domains:
            raise ValueError("workspace snapshot required domains are inconsistent")
        return self


class WorkspaceBenchmarkCase(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyStr
    mode: WorkspaceSnapshotMode
    expected_behavior: WorkspaceAnswerBehavior
    snapshot: ScoutWorkspaceSnapshot
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_case(self) -> "WorkspaceBenchmarkCase":
        if self.snapshot.mode is not self.mode:
            raise ValueError("workspace benchmark mode does not match snapshot")
        if self.snapshot.sufficiency.behavior is not self.expected_behavior:
            raise ValueError("workspace benchmark behavior does not match snapshot")
        return self


class WorkspaceContextBudgetExceeded(RuntimeError):
    pass


class WorkspaceContextCompiler:
    """Compile the smallest typed evidence projection for one task class."""

    def __init__(
        self,
        *,
        context_budget_tokens: int = 4096,
        stale_after_seconds: int = 3600,
    ) -> None:
        if context_budget_tokens < 1:
            raise ValueError("workspace context budget must be positive")
        if stale_after_seconds < 1:
            raise ValueError("workspace stale threshold must be positive")
        self.context_budget_tokens = context_budget_tokens
        self.stale_after_seconds = stale_after_seconds

    def compile(
        self,
        *,
        request: IntelligenceRequest,
        evidence_catalog: EvidenceCatalog,
        authority_by_ref: Mapping[str, WorkspaceAuthority] | None = None,
        now: datetime | None = None,
    ) -> ScoutWorkspaceSnapshot:
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("workspace compilation time must be timezone-aware")
        authorities = authority_by_ref or {}
        resolved, missing_refs = evidence_catalog.resolve(request.evidence_refs)
        facts: list[WorkspaceEvidenceFact] = []
        irrelevant_refs: list[str] = []
        for item in resolved:
            domain = _domain_for_source_type(item.source_type)
            if domain is None or domain not in _required_domains(request.task_type):
                irrelevant_refs.append(item.source_ref)
                continue
            facts.append(
                _fact_from_item(
                    item,
                    domain=domain,
                    authority=authorities.get(
                        item.source_ref,
                        WorkspaceAuthority.CANDIDATE,
                    ),
                    checked_at=checked_at,
                    stale_after_seconds=self.stale_after_seconds,
                )
            )

        required = _required_domains(request.task_type)
        available = tuple(
            domain for domain in required if any(fact.domain is domain for fact in facts)
        )
        missing = tuple(domain for domain in required if domain not in available)
        stale = tuple(
            domain
            for domain in required
            if any(
                fact.domain is domain and fact.status is WorkspaceFactStatus.STALE
                for fact in facts
            )
        )
        conflicted = tuple(
            domain
            for domain in required
            if any(
                fact.domain is domain
                and fact.status is WorkspaceFactStatus.CONFLICTED
                for fact in facts
            )
        )
        behavior = _expected_behavior(
            has_facts=bool(facts),
            missing=bool(missing),
            stale=bool(stale),
            conflicted=bool(conflicted),
        )
        sufficiency = ContextSufficiencyAssessment(
            required_domains=required,
            available_domains=available,
            missing_domains=missing,
            stale_domains=stale,
            conflicted_domains=conflicted,
            missing_evidence_refs=missing_refs,
            sufficient=behavior is WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE,
            behavior=behavior,
        )
        mode = _snapshot_mode(
            has_facts=bool(facts),
            missing=bool(missing),
            stale=bool(stale),
            conflicted=bool(conflicted),
        )
        estimated_tokens = _estimate_tokens(
            {
                "task_type": request.task_type.value,
                "question": request.question,
                "workspace_binding": request.workspace_binding.model_dump(mode="json"),
                "facts": [fact.model_dump(mode="json") for fact in facts],
                "sufficiency": sufficiency.model_dump(mode="json"),
            }
        )
        if estimated_tokens > self.context_budget_tokens:
            raise WorkspaceContextBudgetExceeded(
                f"workspace projection needs {estimated_tokens} tokens but budget is "
                f"{self.context_budget_tokens}"
            )
        snapshot = ScoutWorkspaceSnapshot(
            snapshot_hash="pending",
            compiled_at=checked_at,
            task_type=request.task_type,
            question=request.question,
            workspace_binding=request.workspace_binding,
            mode=mode,
            required_domains=required,
            facts=tuple(facts),
            evidence_refs=tuple(fact.evidence_ref for fact in facts),
            irrelevant_evidence_refs=tuple(irrelevant_refs),
            unknown_provenance_refs=tuple(
                fact.evidence_ref for fact in facts if not fact.content_hash
            ),
            sufficiency=sufficiency,
            context_budget_tokens=self.context_budget_tokens,
            estimated_tokens=estimated_tokens,
        )
        return snapshot.model_copy(
            update={"snapshot_hash": workspace_snapshot_hash(snapshot)}
        )


def build_workspace_benchmark_cases(
    *,
    request: IntelligenceRequest,
    evidence_catalog: EvidenceCatalog,
    compiler: WorkspaceContextCompiler,
    now: datetime,
) -> tuple[WorkspaceBenchmarkCase, ...]:
    route_items = tuple(
        item
        for item in evidence_catalog.items
        if _domain_for_source_type(item.source_type) is WorkspaceDomain.ROUTE
    )
    stale_items = tuple(
        item.model_copy(
            update={
                "generated_at": now
                - timedelta(seconds=compiler.stale_after_seconds + 1)
            }
        )
        for item in evidence_catalog.items
    )
    conflicted_items = list(evidence_catalog.items)
    terrain_index = next(
        index
        for index, item in enumerate(conflicted_items)
        if _domain_for_source_type(item.source_type) is WorkspaceDomain.TERRAIN
    )
    terrain_item = conflicted_items[terrain_index]
    conflicted_items[terrain_index] = terrain_item.model_copy(
        update={
            "attributes": {
                **terrain_item.attributes,
                "conflicts": [
                    {
                        "description": "Terrain evidence sources conflict.",
                        "evidence_refs": list(request.evidence_refs),
                    }
                ],
            }
        }
    )
    inputs = (
        (WorkspaceSnapshotMode.FULL, evidence_catalog),
        (WorkspaceSnapshotMode.MISSING, EvidenceCatalog(items=route_items)),
        (WorkspaceSnapshotMode.STALE, EvidenceCatalog(items=stale_items)),
        (
            WorkspaceSnapshotMode.CONFLICTED,
            EvidenceCatalog(items=tuple(conflicted_items)),
        ),
        (WorkspaceSnapshotMode.NO_WORKSPACE, EvidenceCatalog()),
    )
    cases: list[WorkspaceBenchmarkCase] = []
    for mode, catalog in inputs:
        snapshot = compiler.compile(
            request=request,
            evidence_catalog=catalog,
            now=now,
        )
        cases.append(
            WorkspaceBenchmarkCase(
                case_id=f"terrain-workspace-{mode.value}-v0",
                mode=mode,
                expected_behavior=snapshot.sufficiency.behavior,
                snapshot=snapshot,
            )
        )
    return tuple(cases)


def workspace_snapshot_hash(snapshot: ScoutWorkspaceSnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    payload.pop("snapshot_hash", None)
    payload.pop("snapshot_id", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fact_from_item(
    item: EvidenceCatalogItem,
    *,
    domain: WorkspaceDomain,
    authority: WorkspaceAuthority,
    checked_at: datetime,
    stale_after_seconds: int,
) -> WorkspaceEvidenceFact:
    observed_at = item.observed_at or item.generated_at
    age_seconds = max(0, int((checked_at - observed_at).total_seconds()))
    conflicts = _conflict_descriptions(item)
    status = (
        WorkspaceFactStatus.CONFLICTED
        if conflicts
        else (
            WorkspaceFactStatus.STALE
            if age_seconds > stale_after_seconds
            else WorkspaceFactStatus.AVAILABLE
        )
    )
    return WorkspaceEvidenceFact(
        fact_id=f"workspace:{item.evidence_id}",
        domain=domain,
        status=status,
        authority=authority,
        evidence_id=item.evidence_id,
        evidence_ref=item.source_ref,
        source_type=item.source_type,
        summary=item.summary,
        content_hash=item.content_hash,
        generated_at=item.generated_at,
        observed_at=item.observed_at,
        age_seconds=age_seconds,
        method=item.method,
        resolution=item.resolution,
        candidate_features=_candidate_features(item),
        conflict_descriptions=conflicts,
    )


def _candidate_features(
    item: EvidenceCatalogItem,
) -> tuple[WorkspaceCandidateFeature, ...]:
    raw_features = item.attributes.get("candidate_features", [])
    if not isinstance(raw_features, list):
        return ()
    result: list[WorkspaceCandidateFeature] = []
    for index, feature in enumerate(raw_features):
        if not isinstance(feature, dict) or not str(feature.get("claim") or "").strip():
            continue
        confidence = min(1.0, max(0.0, float(feature.get("confidence", 0.5))))
        result.append(
            WorkspaceCandidateFeature(
                feature_id=(
                    f"workspace:{item.evidence_id}:{index}:"
                    f"{feature.get('kind') or 'candidate'}"
                ),
                kind=str(feature.get("kind") or "candidate"),
                claim=str(feature["claim"]),
                confidence=confidence,
                evidence_id=item.evidence_id,
            )
        )
    return tuple(result)


def _conflict_descriptions(item: EvidenceCatalogItem) -> tuple[str, ...]:
    raw_conflicts = item.attributes.get("conflicts", [])
    if not isinstance(raw_conflicts, list):
        return ()
    return tuple(
        str(conflict["description"]).strip()
        for conflict in raw_conflicts
        if isinstance(conflict, dict)
        and str(conflict.get("description") or "").strip()
    )


def _required_domains(
    task_type: IntelligenceTaskType,
) -> tuple[WorkspaceDomain, ...]:
    if task_type is IntelligenceTaskType.TERRAIN_ANALYSIS:
        return (WorkspaceDomain.ROUTE, WorkspaceDomain.TERRAIN)
    raise ValueError(f"workspace compiler does not support task {task_type.value}")


def _domain_for_source_type(source_type: str) -> WorkspaceDomain | None:
    normalized = source_type.lower()
    if "route" in normalized:
        return WorkspaceDomain.ROUTE
    if any(marker in normalized for marker in ("terrain", "dem", "qgis", "slope")):
        return WorkspaceDomain.TERRAIN
    if "weather" in normalized:
        return WorkspaceDomain.WEATHER
    if any(marker in normalized for marker in ("gnss", "position", "pdr")):
        return WorkspaceDomain.POSITION
    if any(marker in normalized for marker in ("pace", "eta")):
        return WorkspaceDomain.PACE
    return None


def _snapshot_mode(
    *,
    has_facts: bool,
    missing: bool,
    stale: bool,
    conflicted: bool,
) -> WorkspaceSnapshotMode:
    if not has_facts:
        return WorkspaceSnapshotMode.NO_WORKSPACE
    if conflicted:
        return WorkspaceSnapshotMode.CONFLICTED
    if missing:
        return WorkspaceSnapshotMode.MISSING
    if stale:
        return WorkspaceSnapshotMode.STALE
    return WorkspaceSnapshotMode.FULL


def _expected_behavior(
    *,
    has_facts: bool,
    missing: bool,
    stale: bool,
    conflicted: bool,
) -> WorkspaceAnswerBehavior:
    if conflicted:
        return WorkspaceAnswerBehavior.PRESERVE_CONFLICT
    if not has_facts or missing:
        return WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED
    if stale:
        return WorkspaceAnswerBehavior.REFRESH_REQUIRED
    return WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE


def _estimate_tokens(payload: Mapping[str, Any]) -> int:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return max(1, math.ceil(len(encoded) / 4))


__all__ = [
    "ContextSufficiencyAssessment",
    "ScoutWorkspaceSnapshot",
    "WorkspaceAnswerBehavior",
    "WorkspaceAuthority",
    "WorkspaceBenchmarkCase",
    "WorkspaceCandidateFeature",
    "WorkspaceContextBudgetExceeded",
    "WorkspaceContextCompiler",
    "WorkspaceDomain",
    "WorkspaceEvidenceFact",
    "WorkspaceFactStatus",
    "WorkspaceSnapshotMode",
    "build_workspace_benchmark_cases",
    "workspace_snapshot_hash",
]
