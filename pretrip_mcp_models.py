from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceFamily = Literal[
    "ptt_hiking",
    "hiking_biji",
    "sunriver_culture",
    "public_web",
    "reference_gpx",
    "offline_map_ocr",
    "scout_generated_cp",
    "terrain_risk",
]
McpClass = Literal[
    "fork_junction",
    "camp_hut_structure",
    "water_source",
    "extreme_terrain_hazard",
    "hidden_forest_route_loss",
    "viewpoint_trailhead_pass",
    "technical_infrastructure",
    "mobile_reception",
]
Confidence = Literal["low", "medium", "high"]
StaleRisk = Literal["low", "medium", "high"]
ReviewState = Literal["needs_human_review", "suggested_insertion_review_required"]
McpReviewDecision = Literal["accepted", "linked", "split", "downgraded", "rejected"]
McpToolCapability = Literal[
    "search_query_planning",
    "web_search",
    "web_fetch_summary",
    "local_evidence_lookup",
    "ocr_label_normalization",
]
McpCpSupportStatus = Literal["supported", "suggested_insertion_review_required"]


class McpModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpBoundary(McpModel):
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compile_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False


class NamedPointBoundary(McpModel):
    candidate_only: Literal[True] = True
    phase1_runtime_safety_truth: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    full_copyrighted_payload_embedded: Literal[False] = False


class NamedPointSearchProfile(McpModel):
    profile_id: str = "taiwan_hiking_public_sources.v1"
    required_source_families: tuple[SourceFamily, ...] = (
        "ptt_hiking",
        "hiking_biji",
        "sunriver_culture",
    )
    attempted_source_families: tuple[SourceFamily, ...] = (
        "ptt_hiking",
        "hiking_biji",
        "sunriver_culture",
    )
    accepted_evidence_page_count: int = Field(ge=0)
    live_network_performed: Literal[False] = False
    fixture_backed: Literal[True] = True

    @model_validator(mode="after")
    def _require_mandatory_attempts(self) -> "NamedPointSearchProfile":
        missing = set(self.required_source_families) - set(self.attempted_source_families)
        if missing:
            raise ValueError("required source families must be attempted")
        return self


class NamedPointEvidencePage(McpModel):
    page_id: str
    source_family: SourceFamily
    url: str
    canonical_url: str | None = None
    title: str
    retrieved_at: str
    accepted: bool = True
    route_relevance: Confidence = "medium"
    stale_risk: StaleRisk = "low"
    snippet_hash: str
    full_payload_embedded: Literal[False] = False


class NamedPointRoutePosition(McpModel):
    distance_m: float = Field(ge=0)
    lat: float
    lon: float
    coordinate_confidence: Confidence = "medium"


class NearestScoutCp(McpModel):
    candidate_id: str | None = None
    distance_m: float | None = Field(default=None, ge=0)
    support_radius_m: float = Field(ge=0)
    support_found: bool


class NamedPointOcrLabel(McpModel):
    label_text: str
    source_image_hash: str
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)
    source_ref: str
    human_review_required: Literal[True] = True
    full_source_image_embedded: Literal[False] = False


class NamedPoint(McpModel):
    named_point_id: str
    canonical_name: str
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    point_class: tuple[McpClass, ...]
    mention_page_ids: tuple[str, ...]
    mention_page_count: int = Field(ge=0)
    mention_ratio: float = Field(ge=0, le=1)
    source_families: tuple[SourceFamily, ...]
    missing_source_families: tuple[SourceFamily, ...] = Field(default_factory=tuple)
    route_position: NamedPointRoutePosition
    nearest_scout_cp: NearestScoutCp | None = None
    terrain_risk_refs: tuple[str, ...] = Field(default_factory=tuple)
    ocr_labels: tuple[NamedPointOcrLabel, ...] = Field(default_factory=tuple)
    stale_risk: StaleRisk = "low"
    boundary: NamedPointBoundary = Field(default_factory=NamedPointBoundary)

    @model_validator(mode="after")
    def _enforce_counts(self) -> "NamedPoint":
        if self.mention_page_count != len(set(self.mention_page_ids)):
            raise ValueError("mention_page_count must match unique mention_page_ids")
        if not self.point_class:
            raise ValueError("point_class must include at least one MCP class")
        return self


class NamedPointEvidenceSet(McpModel):
    artifact_kind: Literal["pretrip_named_point_evidence_set"] = (
        "pretrip_named_point_evidence_set"
    )
    artifact_version: Literal["named_point_evidence.v1"] = "named_point_evidence.v1"
    project_id: str
    source_path: str
    search_profile: NamedPointSearchProfile
    evidence_pages: tuple[NamedPointEvidencePage, ...]
    named_points: tuple[NamedPoint, ...]
    boundary: NamedPointBoundary = Field(default_factory=NamedPointBoundary)

    @model_validator(mode="after")
    def _enforce_evidence_counts(self) -> "NamedPointEvidenceSet":
        page_by_id = {page.page_id: page for page in self.evidence_pages}
        accepted_count = sum(1 for page in self.evidence_pages if page.accepted)
        if self.search_profile.accepted_evidence_page_count != accepted_count:
            raise ValueError("accepted_evidence_page_count must match accepted pages")
        for named_point in self.named_points:
            missing_pages = set(named_point.mention_page_ids) - set(page_by_id)
            if missing_pages:
                raise ValueError("named point references unknown evidence page")
            accepted_mentions = [
                page_by_id[page_id]
                for page_id in named_point.mention_page_ids
                if page_by_id[page_id].accepted
            ]
            expected_ratio = (
                len(accepted_mentions) / accepted_count if accepted_count else 0.0
            )
            if abs(named_point.mention_ratio - expected_ratio) > 0.001:
                raise ValueError("mention_ratio must match accepted evidence count")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class McpRetrievalQuery(McpModel):
    query_id: str
    query_text: str
    source_family_target: SourceFamily
    generated_at: str
    tool_provider_id: str
    result_count: int = Field(ge=0)
    accepted_result_ids: tuple[str, ...] = Field(default_factory=tuple)
    rejected_result_ids: tuple[str, ...] = Field(default_factory=tuple)
    rejected_reasons: dict[str, str] = Field(default_factory=dict)
    live_network_performed: Literal[False] = False


class McpToolContract(McpModel):
    tool_id: str
    capability: McpToolCapability
    source_family_targets: tuple[SourceFamily, ...]
    input_schema_name: str
    output_schema_name: str
    fixture_backed: Literal[True] = True
    live_network_allowed_in_tests: Literal[False] = False
    runtime_truth_allowed: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class McpFetchSummary(McpModel):
    fetch_id: str
    source_page_id: str
    query_id: str
    source_family: SourceFamily
    url: str
    title: str
    retrieved_at: str
    accepted: bool
    route_relevance: Confidence
    stale_risk: StaleRisk
    snippet_hash: str
    extracted_named_point_ids: tuple[str, ...] = Field(default_factory=tuple)
    full_payload_embedded: Literal[False] = False
    live_network_performed: Literal[False] = False


class McpRetrievalPlan(McpModel):
    artifact_kind: Literal["pretrip_mcp_retrieval_plan"] = (
        "pretrip_mcp_retrieval_plan"
    )
    artifact_version: Literal["mcp_retrieval_plan.v1"] = "mcp_retrieval_plan.v1"
    project_id: str
    route_name: str
    source_profile_id: str
    planner_kind: Literal["pydantic_ai_tool_orchestration_plan"] = (
        "pydantic_ai_tool_orchestration_plan"
    )
    pydantic_ai_responsibility: Literal[
        "search_planning_tool_calls_structured_extraction_only"
    ] = "search_planning_tool_calls_structured_extraction_only"
    truth_decision_allowed: Literal[False] = False
    generated_at: str
    required_source_families: tuple[SourceFamily, ...]
    attempted_source_families: tuple[SourceFamily, ...]
    query_count: int = Field(ge=0)
    queries: tuple[McpRetrievalQuery, ...]
    tool_contracts: tuple[McpToolContract, ...] = Field(default_factory=tuple)
    fetch_summary_count: int = Field(default=0, ge=0)
    fetch_summaries: tuple[McpFetchSummary, ...] = Field(default_factory=tuple)
    accepted_evidence_page_count: int = Field(ge=0)
    candidate_only: Literal[True] = True
    live_network_performed: Literal[False] = False
    fixture_backed: Literal[True] = True
    boundary: McpBoundary = Field(default_factory=McpBoundary)

    @model_validator(mode="after")
    def _enforce_query_count(self) -> "McpRetrievalPlan":
        if self.query_count != len(self.queries):
            raise ValueError("query_count must match queries")
        if self.fetch_summary_count != len(self.fetch_summaries):
            raise ValueError("fetch_summary_count must match fetch_summaries")
        missing = set(self.required_source_families) - set(self.attempted_source_families)
        if missing:
            raise ValueError("required source families must be attempted")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class McpOcrLabel(McpModel):
    ocr_label_id: str
    named_point_id: str
    label_text: str
    source_image_hash: str
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)
    source_ref: str
    review_required: Literal[True] = True
    candidate_only: Literal[True] = True
    full_source_image_embedded: Literal[False] = False


class McpOcrLabelSet(McpModel):
    artifact_kind: Literal["pretrip_mcp_ocr_label_set"] = (
        "pretrip_mcp_ocr_label_set"
    )
    artifact_version: Literal["mcp_ocr_labels.v1"] = "mcp_ocr_labels.v1"
    project_id: str
    source_refs: tuple[str, ...]
    label_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    labels: tuple[McpOcrLabel, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    full_source_image_embedded: Literal[False] = False
    boundary: McpBoundary = Field(default_factory=McpBoundary)

    @model_validator(mode="after")
    def _enforce_counts(self) -> "McpOcrLabelSet":
        if self.label_count != len(self.labels):
            raise ValueError("label_count must match labels")
        review_required = sum(1 for label in self.labels if label.review_required)
        if self.review_required_count != review_required:
            raise ValueError("review_required_count must match labels")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class McpPolicy(McpModel):
    min_spacing_m: float = Field(default=1000.0, ge=0)
    scout_cp_support_radius_m: float = Field(default=250.0, ge=0)
    np_min_mention_ratio: float = Field(default=0.05, ge=0, le=1)
    np_min_accepted_evidence_pages: int = Field(default=11, ge=0)
    required_source_families: tuple[SourceFamily, ...] = (
        "ptt_hiking",
        "hiking_biji",
        "sunriver_culture",
    )
    type_weights: dict[McpClass, float] = Field(
        default_factory=lambda: {
            "extreme_terrain_hazard": 30.0,
            "fork_junction": 25.0,
            "camp_hut_structure": 25.0,
            "water_source": 25.0,
            "technical_infrastructure": 22.0,
            "viewpoint_trailhead_pass": 20.0,
            "mobile_reception": 18.0,
            "hidden_forest_route_loss": 18.0,
        }
    )


class McpScoreComponents(McpModel):
    type_weight: float
    named_point_support: float
    source_family_diversity: float
    scout_cp_support: float
    terrain_risk_support: float
    stale_source_penalty: float
    coordinate_uncertainty_penalty: float
    total: float


class McpSpacingSuppression(McpModel):
    source_id: str
    label: str
    distance_m: float = Field(ge=0)
    source_distance_m: float = Field(ge=0)
    spacing_threshold_m: float = Field(ge=0)
    reason: str
    score: float


class McpSuggestedInsertion(McpModel):
    reason: str
    lat: float
    lon: float
    distance_m: float = Field(ge=0)
    review_required: Literal[True] = True


class McpCandidate(McpModel):
    mcp_id: str
    label: str
    mcp_classes: tuple[McpClass, ...]
    distance_m: float = Field(ge=0)
    lat: float
    lon: float
    confidence: Confidence
    score_components: McpScoreComponents
    mention_ratio: float = Field(ge=0, le=1)
    accepted_evidence_page_count: int = Field(ge=0)
    source_family_coverage: dict[str, object]
    nearest_scout_cp: NearestScoutCp
    promotion_reasons: tuple[str, ...]
    missing_source_gaps: tuple[str, ...] = Field(default_factory=tuple)
    linked_named_points: tuple[str, ...]
    linked_cp_candidates: tuple[str, ...] = Field(default_factory=tuple)
    linked_risk_segments: tuple[str, ...] = Field(default_factory=tuple)
    nearby_points_suppressed_by_spacing: tuple[McpSpacingSuppression, ...] = (
        Field(default_factory=tuple)
    )
    suggested_cp_insertion: McpSuggestedInsertion | None = None
    review_state: ReviewState = "needs_human_review"
    boundary: McpBoundary = Field(default_factory=McpBoundary)


class McpCandidateSet(McpModel):
    artifact_kind: Literal["pretrip_major_critical_point_candidates"] = (
        "pretrip_major_critical_point_candidates"
    )
    artifact_version: Literal["mcp_candidates.v1"] = "mcp_candidates.v1"
    project_id: str
    source_refs: tuple[str, ...]
    mcp_policy: McpPolicy
    dense_checkpoint_count: int = Field(ge=0)
    mcp_candidate_count: int = Field(ge=0)
    compressed_from_dense_cp: bool
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compile_allowed: Literal[False] = False
    mcp_candidates: tuple[McpCandidate, ...]
    suppressed_point_count: int = Field(ge=0)
    boundary: McpBoundary = Field(default_factory=McpBoundary)

    @model_validator(mode="after")
    def _enforce_counts(self) -> "McpCandidateSet":
        if self.mcp_candidate_count != len(self.mcp_candidates):
            raise ValueError("mcp_candidate_count must match mcp_candidates")
        suppressed = sum(
            len(candidate.nearby_points_suppressed_by_spacing)
            for candidate in self.mcp_candidates
        )
        if self.suppressed_point_count != suppressed:
            raise ValueError("suppressed_point_count must match candidate details")
        if self.dense_checkpoint_count:
            expected = len(self.mcp_candidates) < self.dense_checkpoint_count
            if self.compressed_from_dense_cp != expected:
                raise ValueError("compressed_from_dense_cp must match MCP vs dense CP count")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class McpCpSupportRow(McpModel):
    mcp_id: str
    label: str
    distance_m: float = Field(ge=0)
    nearest_scout_cp: NearestScoutCp
    support_status: McpCpSupportStatus
    recommendation: str
    linked_cp_candidates: tuple[str, ...] = Field(default_factory=tuple)
    suggested_cp_insertion: McpSuggestedInsertion | None = None
    suppressed_point_count: int = Field(ge=0)
    spacing_suppression_details: tuple[McpSpacingSuppression, ...] = (
        Field(default_factory=tuple)
    )
    review_required: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compile_allowed: Literal[False] = False


class McpCpSupportReconciliation(McpModel):
    artifact_kind: Literal["pretrip_mcp_cp_support_reconciliation"] = (
        "pretrip_mcp_cp_support_reconciliation"
    )
    artifact_version: Literal["mcp_cp_support_reconciliation.v1"] = (
        "mcp_cp_support_reconciliation.v1"
    )
    project_id: str
    source_candidate_set_ref: str
    support_radius_m: float = Field(ge=0)
    mcp_candidate_count: int = Field(ge=0)
    supported_count: int = Field(ge=0)
    suggested_insertion_count: int = Field(ge=0)
    rows: tuple[McpCpSupportRow, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compile_allowed: Literal[False] = False
    boundary: McpBoundary = Field(default_factory=McpBoundary)

    @model_validator(mode="after")
    def _enforce_counts(self) -> "McpCpSupportReconciliation":
        if self.mcp_candidate_count != len(self.rows):
            raise ValueError("mcp_candidate_count must match rows")
        supported = sum(1 for row in self.rows if row.support_status == "supported")
        suggested = sum(
            1
            for row in self.rows
            if row.support_status == "suggested_insertion_review_required"
        )
        if self.supported_count != supported:
            raise ValueError("supported_count must match rows")
        if self.suggested_insertion_count != suggested:
            raise ValueError("suggested_insertion_count must match rows")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class McpReviewAction(McpModel):
    action_id: str
    mcp_id: str
    decision: McpReviewDecision
    reviewer_alias: str
    decided_at: str
    summary: str
    candidate_label: str | None = None
    nearest_scout_cp_distance_m: float | None = Field(default=None, ge=0)
    source_family_coverage: dict[str, object] = Field(default_factory=dict)
    support_status: McpCpSupportStatus | None = None
    linked_cp_candidate_id: str | None = None
    split_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    downgrade_reason: str | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compile_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _enforce_decision_detail(self) -> "McpReviewAction":
        if self.decision == "linked" and not self.linked_cp_candidate_id:
            raise ValueError("linked MCP review action requires linked_cp_candidate_id")
        if self.decision == "split" and not self.split_target_ids:
            raise ValueError("split MCP review action requires split_target_ids")
        if self.decision == "downgraded" and not self.downgrade_reason:
            raise ValueError("downgraded MCP review action requires downgrade_reason")
        return self


class McpReviewActionLog(McpModel):
    artifact_kind: Literal["pretrip_mcp_review_action_log"] = (
        "pretrip_mcp_review_action_log"
    )
    artifact_version: Literal["mcp_review_actions.v1"] = "mcp_review_actions.v1"
    project_id: str
    source_candidate_set_ref: str
    action_count: int = Field(ge=0)
    actions: tuple[McpReviewAction, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compile_allowed: Literal[False] = False
    boundary: McpBoundary = Field(default_factory=McpBoundary)

    @model_validator(mode="after")
    def _enforce_action_count(self) -> "McpReviewActionLog":
        if self.action_count != len(self.actions):
            raise ValueError("action_count must match actions")
        if len({action.action_id for action in self.actions}) != len(self.actions):
            raise ValueError("duplicate MCP review action_id")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
