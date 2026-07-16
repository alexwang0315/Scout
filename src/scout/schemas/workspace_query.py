"""Typed contracts for deterministic, read-only workspace queries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, TypeAdapter, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


SAFE_FIELD_PATTERN = r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$"
SafeField = Annotated[str, Field(pattern=SAFE_FIELD_PATTERN, max_length=240)]
WorkspaceQueryStatus: TypeAlias = Literal["success", "warning", "error"]
WorkspaceQueryAnswerability: TypeAlias = Literal[
    "complete",
    "partial",
    "requires_followup_query",
    "missing_artifact",
    "missing_required_fields",
    "stale",
    "candidate_only",
    "requires_live_state",
    "requires_human_review",
    "unsafe_to_infer",
]


class WorkspaceQueryOperation(StrEnum):
    INSPECT = "inspect"
    EXISTS = "exists"
    COUNT = "count"
    DISTINCT = "distinct"
    FILTER = "filter"
    GROUP_BY = "group_by"
    TOP_K = "top_k"
    ARGMAX = "argmax"
    DIFF = "diff"
    FRESHNESS = "freshness"
    NEAREST = "nearest"
    INTERVAL = "interval"
    ROUTE_FORWARD = "route_forward"


class WorkspacePredicateOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    CONTAINS = "contains"
    EXISTS = "exists"


class WorkspaceArtifactSelector(SchemaModel):
    source_ref: str | None = Field(default=None, min_length=1, max_length=500)
    project_ref_key: SafeField | None = None
    collection_path: SafeField | None = None

    @model_validator(mode="after")
    def require_exactly_one_ref(self) -> "WorkspaceArtifactSelector":
        if (self.source_ref is None) == (self.project_ref_key is None):
            raise ValueError("provide exactly one of source_ref or project_ref_key")
        return self


class WorkspacePredicate(SchemaModel):
    field: SafeField
    operator: WorkspacePredicateOperator = WorkspacePredicateOperator.EQ
    value: Any = None


class WorkspaceQueryLimits(SchemaModel):
    max_artifact_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=64 * 1024 * 1024,
    )
    max_scanned_records: int = Field(default=20_000, ge=1, le=100_000)
    max_returned_records: int = Field(default=100, ge=1, le=500)
    max_json_depth: int = Field(default=16, ge=2, le=32)
    max_string_length: int = Field(default=65_536, ge=64, le=1_000_000)
    max_diff_paths: int = Field(default=100, ge=1, le=1_000)


class _CollectionRequest(SchemaModel):
    artifact: WorkspaceArtifactSelector
    predicates: list[WorkspacePredicate] = Field(default_factory=list, max_length=20)
    fields: list[SafeField] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=20, ge=1, le=100)


class InspectQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.INSPECT]


class ExistsQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.EXISTS]
    field: SafeField | None = None


class CountQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.COUNT]


class DistinctQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.DISTINCT]
    field: SafeField


class FilterQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.FILTER]
    sort_by: SafeField | None = None
    descending: bool = False


class GroupByQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.GROUP_BY]
    field: SafeField


class TopKQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.TOP_K]
    field: SafeField
    k: int = Field(default=5, ge=1, le=100)
    descending: bool = True


class ArgMaxQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.ARGMAX]
    field: SafeField
    subtract_field: SafeField | None = None


class DiffQuery(SchemaModel):
    operation: Literal[WorkspaceQueryOperation.DIFF]
    left_artifact: WorkspaceArtifactSelector
    right_artifact: WorkspaceArtifactSelector
    aggregation: Literal["max", "min"] | None = None
    left_field: SafeField | None = None
    right_field: SafeField | None = None

    @model_validator(mode="after")
    def validate_aggregate_diff(self) -> "DiffQuery":
        aggregate_fields = (self.aggregation, self.left_field, self.right_field)
        provided = sum(value is not None for value in aggregate_fields)
        if provided not in {0, len(aggregate_fields)}:
            raise ValueError(
                "aggregation, left_field, and right_field must be provided together"
            )
        return self


class FreshnessQuery(SchemaModel):
    operation: Literal[WorkspaceQueryOperation.FRESHNESS]
    artifact: WorkspaceArtifactSelector
    timestamp_field: SafeField | None = None
    now: datetime | None = None
    stale_after_seconds: float = Field(default=86_400.0, gt=0.0)


class Coordinate(SchemaModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class NearestQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.NEAREST]
    origin: Coordinate
    lat_field: SafeField = "lat"
    lon_field: SafeField = "lon"
    k: int = Field(default=1, ge=1, le=100)
    max_distance_m: float | None = Field(default=None, gt=0.0)


class IntervalQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.INTERVAL]
    value_field: SafeField | None = None
    start: float | None = None
    end: float | None = None
    start_field: SafeField | None = None
    end_field: SafeField | None = None
    cumulative_field: SafeField | None = None
    value: float | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> "IntervalQuery":
        range_mode = all(
            value is not None for value in (self.value_field, self.start, self.end)
        )
        containment_mode = all(
            value is not None for value in (self.start_field, self.end_field, self.value)
        )
        cumulative_mode = self.cumulative_field is not None and self.value is not None
        if sum((range_mode, containment_mode, cumulative_mode)) != 1:
            raise ValueError(
                "provide exactly one interval mode: range, containing fields, or cumulative field"
            )
        if range_mode and self.end is not None and self.start is not None and self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class RouteForwardQuery(_CollectionRequest):
    operation: Literal[WorkspaceQueryOperation.ROUTE_FORWARD]
    route_artifact: WorkspaceArtifactSelector
    route_distance_field: SafeField = "route_distance_m"
    lat_field: SafeField = "lat"
    lon_field: SafeField = "lon"
    current_route_distance_m: float | None = Field(default=None, ge=0.0)
    current_position: Coordinate | None = None
    max_forward_distance_m: float | None = Field(default=None, gt=0.0)


WorkspaceQueryRequest: TypeAlias = Annotated[
    InspectQuery
    | ExistsQuery
    | CountQuery
    | DistinctQuery
    | FilterQuery
    | GroupByQuery
    | TopKQuery
    | ArgMaxQuery
    | DiffQuery
    | FreshnessQuery
    | NearestQuery
    | IntervalQuery
    | RouteForwardQuery,
    Field(discriminator="operation"),
]
_REQUEST_ADAPTER = TypeAdapter(WorkspaceQueryRequest)


def parse_workspace_query_request(value: object) -> WorkspaceQueryRequest:
    return _REQUEST_ADAPTER.validate_python(value)


class WorkspaceQueryEvidence(SchemaModel):
    evidence_id: NonEmptyStr
    source_ref: NonEmptyStr
    record_id: NonEmptyStr
    locator: NonEmptyStr
    source_hash: NonEmptyStr
    data: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class WorkspaceQueryResponse(SchemaModel):
    status: WorkspaceQueryStatus
    answerability: WorkspaceQueryAnswerability
    operation: WorkspaceQueryOperation
    summary: str = ""
    results: list[WorkspaceQueryEvidence] = Field(default_factory=list, max_length=500)
    result_count: int = Field(default=0, ge=0)
    scanned_record_count: int = Field(default=0, ge=0)
    source_refs: list[NonEmptyStr] = Field(default_factory=list, max_length=20)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    freshness: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    safe_retry: bool = False
    stop_condition: str | None = None


class WorkspaceMileageCandidate(SchemaModel):
    """One deduplicated route-label candidate used by deterministic verification."""

    source_label: NonEmptyStr
    label_mileage_k: float
    delta_k: float = Field(ge=0.0)
    direction: Literal["behind", "at", "ahead"]
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    route_distance_m: float | None = Field(default=None, ge=0.0)
    route_projection_status: str | None = None
    source_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    record_ids: list[NonEmptyStr] = Field(default_factory=list)
    source_ref: NonEmptyStr
    source_hashes: list[NonEmptyStr] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class WorkspaceMileageVerification(SchemaModel):
    """Post-model proof for nearest candidates expressed on a signed K-label axis."""

    status: WorkspaceQueryStatus
    target_mileage_k: float
    candidate_kind: Literal["water_source"] = "water_source"
    evidence_record_count: int = Field(ge=0)
    distinct_candidate_count: int = Field(ge=0)
    nearest_delta_k: float | None = Field(default=None, ge=0.0)
    tied_candidate_count: int = Field(ge=0)
    candidates: list[WorkspaceMileageCandidate] = Field(default_factory=list)
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)
    contradictions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    summary: NonEmptyStr
    stop_condition: NonEmptyStr
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


__all__ = [
    "Coordinate",
    "WorkspaceArtifactSelector",
    "WorkspacePredicate",
    "WorkspacePredicateOperator",
    "WorkspaceQueryEvidence",
    "WorkspaceQueryAnswerability",
    "WorkspaceQueryLimits",
    "WorkspaceMileageCandidate",
    "WorkspaceMileageVerification",
    "WorkspaceQueryOperation",
    "WorkspaceQueryRequest",
    "WorkspaceQueryResponse",
    "WorkspaceQueryStatus",
    "parse_workspace_query_request",
]
