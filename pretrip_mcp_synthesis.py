from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from geo_utils import haversine_m
from pretrip_mcp_models import (
    Confidence,
    McpCandidate,
    McpCandidateSet,
    McpCpSupportReconciliation,
    McpCpSupportRow,
    McpFetchSummary,
    McpOcrLabel,
    McpOcrLabelSet,
    McpPolicy,
    McpRetrievalPlan,
    McpRetrievalQuery,
    McpScoreComponents,
    McpSpacingSuppression,
    McpSuggestedInsertion,
    McpToolContract,
    NamedPoint,
    NamedPointEvidenceSet,
    NearestScoutCp,
    SourceFamily,
)


DEFAULT_OUTPUT_NAME = "mcp_candidates.json"
DEFAULT_RETRIEVAL_PLAN_OUTPUT_NAME = "mcp_retrieval_plan.json"
DEFAULT_OCR_LABEL_OUTPUT_NAME = "mcp_ocr_labels.json"
DEFAULT_CP_SUPPORT_RECONCILIATION_OUTPUT_NAME = "mcp_cp_support_reconciliation.json"
MCP_SYNTHESIS_EXTRACTOR_VERSION = "pretrip_mcp_synthesis.v1"
MCP_SYNTHESIS_PROMPT_VERSION = "fixture_backed_pydantic_ai_tool_plan.v1"


@dataclass(frozen=True)
class _ScoutCheckpoint:
    candidate_id: str
    lat: float
    lon: float


@dataclass(frozen=True)
class _ScoredMcp:
    named_point: NamedPoint
    score_components: McpScoreComponents
    confidence: Confidence
    nearest_scout_cp: NearestScoutCp
    promotion_reasons: tuple[str, ...]
    missing_source_gaps: tuple[str, ...]
    suggested_cp_insertion: McpSuggestedInsertion | None


def synthesize_mcp_candidates(
    evidence_set: NamedPointEvidenceSet,
    *,
    project_root: Path | str | None = None,
    policy: McpPolicy | None = None,
    source_refs: Sequence[str] | None = None,
) -> McpCandidateSet:
    effective_policy = policy or McpPolicy(
        required_source_families=evidence_set.search_profile.required_source_families
    )
    checkpoints = _load_scout_checkpoints(project_root)
    accepted_page_count = evidence_set.search_profile.accepted_evidence_page_count
    source_ref_tuple = tuple(source_refs or (evidence_set.source_path,))
    scored = [
        scored_candidate
        for named_point in evidence_set.named_points
        if (
            scored_candidate := _score_named_point(
                named_point,
                accepted_page_count=accepted_page_count,
                policy=effective_policy,
                checkpoints=checkpoints,
            )
        )
        is not None
    ]
    selected, suppressed_by_primary_id = _apply_spacing(scored, effective_policy)
    candidates = tuple(
        _to_mcp_candidate(
            index,
            scored_candidate,
            accepted_page_count=accepted_page_count,
            policy=effective_policy,
            source_refs=source_ref_tuple,
            suppressed=suppressed_by_primary_id.get(
                scored_candidate.named_point.named_point_id,
                (),
            ),
        )
        for index, scored_candidate in enumerate(
            sorted(selected, key=lambda item: item.named_point.route_position.distance_m),
            start=1,
        )
    )
    return McpCandidateSet(
        project_id=evidence_set.project_id,
        source_refs=source_ref_tuple,
        mcp_policy=effective_policy,
        dense_checkpoint_count=len(checkpoints),
        mcp_candidate_count=len(candidates),
        compressed_from_dense_cp=len(candidates) < len(checkpoints) if checkpoints else False,
        mcp_candidates=candidates,
        suppressed_point_count=sum(
            len(candidate.nearby_points_suppressed_by_spacing)
            for candidate in candidates
        ),
    )


def load_named_point_evidence(path: Path | str) -> NamedPointEvidenceSet:
    return NamedPointEvidenceSet.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_mcp_candidate_set(candidate_set: McpCandidateSet, output_path: Path | str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(candidate_set.to_json(), encoding="utf-8")


def build_fixture_backed_retrieval_plan(
    evidence_set: NamedPointEvidenceSet,
    *,
    route_name: str,
    generated_at: str = "2026-05-27T00:00:00+08:00",
    tool_provider_id: str = "pydantic_ai_fixture_tools.v1",
) -> McpRetrievalPlan:
    pages_by_family: dict[SourceFamily, list[str]] = {
        family: [] for family in evidence_set.search_profile.required_source_families
    }
    for page in evidence_set.evidence_pages:
        if page.accepted:
            pages_by_family.setdefault(page.source_family, []).append(page.page_id)
    queries: list[McpRetrievalQuery] = []
    for index, family in enumerate(evidence_set.search_profile.required_source_families, start=1):
        queries.append(
            McpRetrievalQuery(
                query_id=f"mcp.query.{index:03d}.{family}",
                query_text=_query_text_for_family(route_name, family),
                source_family_target=family,
                generated_at=generated_at,
                tool_provider_id=tool_provider_id,
                result_count=len(pages_by_family.get(family, [])),
                accepted_result_ids=tuple(pages_by_family.get(family, [])),
                rejected_result_ids=(),
            )
        )
    alias_start = len(queries) + 1
    for offset, named_point in enumerate(evidence_set.named_points[:8]):
        family = (
            named_point.source_families[0]
            if named_point.source_families
            else evidence_set.search_profile.required_source_families[0]
        )
        queries.append(
            McpRetrievalQuery(
                query_id=f"mcp.query.{alias_start + offset:03d}.{named_point.named_point_id}",
                query_text=f"{route_name} {named_point.canonical_name} 登山",
                source_family_target=family,
                generated_at=generated_at,
                tool_provider_id=tool_provider_id,
                result_count=named_point.mention_page_count,
                accepted_result_ids=named_point.mention_page_ids,
                rejected_result_ids=(),
            )
        )
    first_query_by_family = {
        query.source_family_target: query.query_id
        for query in queries
        if query.source_family_target in evidence_set.search_profile.required_source_families
    }
    fetch_summaries = tuple(
        McpFetchSummary(
            fetch_id=f"mcp.fetch.{index:03d}.{page.page_id}",
            source_page_id=page.page_id,
            query_id=first_query_by_family.get(
                page.source_family,
                queries[0].query_id if queries else "mcp.query.unplanned",
            ),
            source_family=page.source_family,
            url=page.url,
            title=page.title,
            retrieved_at=page.retrieved_at,
            accepted=page.accepted,
            route_relevance=page.route_relevance,
            stale_risk=page.stale_risk,
            snippet_hash=page.snippet_hash,
            extracted_named_point_ids=tuple(
                named_point.named_point_id
                for named_point in evidence_set.named_points
                if page.page_id in named_point.mention_page_ids
            ),
        )
        for index, page in enumerate(evidence_set.evidence_pages, start=1)
        if page.accepted
    )
    attempted = evidence_set.search_profile.attempted_source_families
    return McpRetrievalPlan(
        project_id=evidence_set.project_id,
        route_name=route_name,
        source_profile_id=evidence_set.search_profile.profile_id,
        generated_at=generated_at,
        required_source_families=evidence_set.search_profile.required_source_families,
        attempted_source_families=attempted,
        query_count=len(queries),
        queries=tuple(queries),
        tool_contracts=_fixture_tool_contracts(
            evidence_set.search_profile.required_source_families,
        ),
        fetch_summary_count=len(fetch_summaries),
        fetch_summaries=fetch_summaries,
        accepted_evidence_page_count=evidence_set.search_profile.accepted_evidence_page_count,
    )


def normalize_ocr_labels_from_evidence(
    evidence_set: NamedPointEvidenceSet,
    *,
    source_refs: Sequence[str] | None = None,
) -> McpOcrLabelSet:
    labels: list[McpOcrLabel] = []
    for named_point in evidence_set.named_points:
        for index, label in enumerate(named_point.ocr_labels, start=1):
            labels.append(
                McpOcrLabel(
                    ocr_label_id=f"ocr.{named_point.named_point_id.removeprefix('np.')}.{index:03d}",
                    named_point_id=named_point.named_point_id,
                    label_text=label.label_text,
                    source_image_hash=label.source_image_hash,
                    bbox=label.bbox,
                    confidence=label.confidence,
                    source_ref=label.source_ref,
                )
            )
    return McpOcrLabelSet(
        project_id=evidence_set.project_id,
        source_refs=tuple(source_refs or (evidence_set.source_path,)),
        label_count=len(labels),
        review_required_count=sum(1 for label in labels if label.review_required),
        labels=tuple(labels),
    )


def write_retrieval_plan(plan: McpRetrievalPlan, output_path: Path | str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(plan.to_json(), encoding="utf-8")


def write_ocr_label_set(label_set: McpOcrLabelSet, output_path: Path | str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(label_set.to_json(), encoding="utf-8")


def build_cp_support_reconciliation(
    candidate_set: McpCandidateSet,
    *,
    source_candidate_set_ref: str,
) -> McpCpSupportReconciliation:
    rows: list[McpCpSupportRow] = []
    for candidate in candidate_set.mcp_candidates:
        support_found = candidate.nearest_scout_cp.support_found
        support_status = (
            "supported"
            if support_found
            else "suggested_insertion_review_required"
        )
        recommendation = (
            "Link MCP review action to the nearest Scout CP candidate."
            if support_found
            else (
                "No Scout CP support within policy radius; keep candidate "
                "review-required and create a suggested CP insertion."
            )
        )
        rows.append(
            McpCpSupportRow(
                mcp_id=candidate.mcp_id,
                label=candidate.label,
                distance_m=candidate.distance_m,
                nearest_scout_cp=candidate.nearest_scout_cp,
                support_status=support_status,
                recommendation=recommendation,
                linked_cp_candidates=candidate.linked_cp_candidates,
                suggested_cp_insertion=candidate.suggested_cp_insertion,
                suppressed_point_count=len(candidate.nearby_points_suppressed_by_spacing),
                spacing_suppression_details=candidate.nearby_points_suppressed_by_spacing,
            )
        )
    return McpCpSupportReconciliation(
        project_id=candidate_set.project_id,
        source_candidate_set_ref=source_candidate_set_ref,
        support_radius_m=candidate_set.mcp_policy.scout_cp_support_radius_m,
        mcp_candidate_count=len(rows),
        supported_count=sum(1 for row in rows if row.support_status == "supported"),
        suggested_insertion_count=sum(
            1
            for row in rows
            if row.support_status == "suggested_insertion_review_required"
        ),
        rows=tuple(rows),
    )


def load_mcp_candidate_set(path: Path | str) -> McpCandidateSet:
    return McpCandidateSet.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_cp_support_reconciliation(
    reconciliation: McpCpSupportReconciliation,
    output_path: Path | str,
) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(reconciliation.to_json(), encoding="utf-8")


def _score_named_point(
    named_point: NamedPoint,
    *,
    accepted_page_count: int,
    policy: McpPolicy,
    checkpoints: Sequence[_ScoutCheckpoint],
) -> _ScoredMcp | None:
    if accepted_page_count < policy.np_min_accepted_evidence_pages:
        return None
    if named_point.mention_ratio < policy.np_min_mention_ratio:
        return None

    nearest = _nearest_scout_cp(named_point, checkpoints, policy)
    source_families = set(named_point.source_families)
    missing_required = tuple(
        family
        for family in policy.required_source_families
        if family not in source_families
    )
    type_weight = max(
        policy.type_weights[point_class]
        for point_class in named_point.point_class
    )
    named_point_support = min(25.0, named_point.mention_ratio * 100.0)
    source_family_diversity = min(18.0, len(source_families) * 4.0)
    if not missing_required:
        source_family_diversity += 4.0
    scout_cp_support = 15.0 if nearest.support_found else -10.0
    terrain_risk_support = 8.0 if named_point.terrain_risk_refs else 0.0
    stale_source_penalty = {
        "low": 0.0,
        "medium": 4.0,
        "high": 10.0,
    }[named_point.stale_risk]
    coordinate_uncertainty_penalty = {
        "high": 0.0,
        "medium": 3.0,
        "low": 8.0,
    }[named_point.route_position.coordinate_confidence]
    total = round(
        type_weight
        + named_point_support
        + source_family_diversity
        + scout_cp_support
        + terrain_risk_support
        - stale_source_penalty
        - coordinate_uncertainty_penalty,
        3,
    )
    components = McpScoreComponents(
        type_weight=type_weight,
        named_point_support=round(named_point_support, 3),
        source_family_diversity=round(source_family_diversity, 3),
        scout_cp_support=scout_cp_support,
        terrain_risk_support=terrain_risk_support,
        stale_source_penalty=stale_source_penalty,
        coordinate_uncertainty_penalty=coordinate_uncertainty_penalty,
        total=total,
    )
    missing_gaps = tuple(
        f"missing mandatory source family: {family}" for family in missing_required
    )
    confidence = _confidence_for(
        named_point,
        missing_required=missing_required,
        nearest_scout_cp=nearest,
        accepted_page_count=accepted_page_count,
        policy=policy,
    )
    insertion = None
    if not nearest.support_found:
        insertion = McpSuggestedInsertion(
            reason=(
                "No Scout CP support within policy radius; create suggested "
                "candidate insertion for human review."
            ),
            lat=named_point.route_position.lat,
            lon=named_point.route_position.lon,
            distance_m=named_point.route_position.distance_m,
        )
    return _ScoredMcp(
        named_point=named_point,
        score_components=components,
        confidence=confidence,
        nearest_scout_cp=nearest,
        promotion_reasons=_promotion_reasons(
            named_point,
            nearest_scout_cp=nearest,
            accepted_page_count=accepted_page_count,
            missing_required=missing_required,
        ),
        missing_source_gaps=missing_gaps,
        suggested_cp_insertion=insertion,
    )


def _apply_spacing(
    scored: Sequence[_ScoredMcp],
    policy: McpPolicy,
) -> tuple[tuple[_ScoredMcp, ...], dict[str, tuple[McpSpacingSuppression, ...]]]:
    selected: list[_ScoredMcp] = []
    suppressed: dict[str, list[McpSpacingSuppression]] = {}
    for candidate in sorted(
        scored,
        key=lambda item: (
            -item.score_components.total,
            item.named_point.route_position.distance_m,
            item.named_point.named_point_id,
        ),
    ):
        primary = _selected_within_spacing(candidate, selected, policy)
        if primary is None:
            selected.append(candidate)
            continue
        spacing_distance = abs(
            candidate.named_point.route_position.distance_m
            - primary.named_point.route_position.distance_m
        )
        suppressed.setdefault(primary.named_point.named_point_id, []).append(
            McpSpacingSuppression(
                source_id=candidate.named_point.named_point_id,
                label=candidate.named_point.canonical_name,
                distance_m=candidate.named_point.route_position.distance_m,
                source_distance_m=round(spacing_distance, 3),
                spacing_threshold_m=policy.min_spacing_m,
                reason=(
                    "within primary MCP spacing window; preserved as linked "
                    "suppressed point"
                ),
                score=candidate.score_components.total,
            )
        )
    return tuple(selected), {
        key: tuple(value)
        for key, value in suppressed.items()
    }


def _selected_within_spacing(
    candidate: _ScoredMcp,
    selected: Sequence[_ScoredMcp],
    policy: McpPolicy,
) -> _ScoredMcp | None:
    for primary in selected:
        spacing_distance = abs(
            candidate.named_point.route_position.distance_m
            - primary.named_point.route_position.distance_m
        )
        if spacing_distance < policy.min_spacing_m:
            return primary
    return None


def _to_mcp_candidate(
    index: int,
    scored: _ScoredMcp,
    *,
    accepted_page_count: int,
    policy: McpPolicy,
    source_refs: Sequence[str],
    suppressed: Sequence[McpSpacingSuppression],
) -> McpCandidate:
    named_point = scored.named_point
    linked_named_points = tuple(
        [named_point.named_point_id]
        + [item.source_id for item in suppressed]
    )
    linked_cp_candidates = (
        (scored.nearest_scout_cp.candidate_id,)
        if scored.nearest_scout_cp.candidate_id
        else ()
    )
    candidate_source_refs = tuple(
        dict.fromkeys(
            [
                *source_refs,
                *named_point.mention_page_ids,
                *named_point.terrain_risk_refs,
            ]
        )
    )
    model_output_summary = (
        "Fixture-backed MCP synthesis compressed named-point, source-family, "
        "Scout CP support, and terrain-risk evidence into a review-gated major "
        "critical point candidate; candidate-only evidence."
    )
    return McpCandidate(
        mcp_id=f"mcp.{named_point.named_point_id.removeprefix('np.')}.{index:03d}",
        label=named_point.canonical_name,
        mcp_classes=named_point.point_class,
        distance_m=named_point.route_position.distance_m,
        lat=named_point.route_position.lat,
        lon=named_point.route_position.lon,
        confidence=scored.confidence,
        score_components=scored.score_components,
        mention_ratio=named_point.mention_ratio,
        accepted_evidence_page_count=accepted_page_count,
        source_family_coverage=_source_family_coverage(named_point, policy),
        nearest_scout_cp=scored.nearest_scout_cp,
        promotion_reasons=scored.promotion_reasons,
        missing_source_gaps=scored.missing_source_gaps,
        linked_named_points=linked_named_points,
        linked_cp_candidates=linked_cp_candidates,
        linked_risk_segments=named_point.terrain_risk_refs,
        nearby_points_suppressed_by_spacing=tuple(suppressed),
        suggested_cp_insertion=scored.suggested_cp_insertion,
        source_refs=candidate_source_refs,
        source_attribution=(
            {
                "source_kind": "named_point_evidence",
                "source_artifact_id": source_refs[0] if source_refs else "",
                "source_role": "mcp_named_point_synthesis_input",
                "named_point_id": named_point.named_point_id,
                "mention_page_ids": list(named_point.mention_page_ids),
                "source_families": list(named_point.source_families),
                "confidence": scored.confidence,
                "stale_risk": named_point.stale_risk,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "source_kind": "scout_generated_cp",
                "source_role": "nearest_cp_support",
                "candidate_id": scored.nearest_scout_cp.candidate_id,
                "distance_m": scored.nearest_scout_cp.distance_m,
                "support_found": scored.nearest_scout_cp.support_found,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ),
        extractor_version=MCP_SYNTHESIS_EXTRACTOR_VERSION,
        pydantic_ai_prompt_version=MCP_SYNTHESIS_PROMPT_VERSION,
        model_output_sha256=_mcp_candidate_hash(
            named_point=named_point,
            policy=policy,
            linked_named_points=linked_named_points,
            linked_cp_candidates=linked_cp_candidates,
        ),
        model_output_summary=model_output_summary,
        stale_risk=named_point.stale_risk,
        candidate_only=True,
        runtime_safety_truth=False,
        review_state=(
            "suggested_insertion_review_required"
            if scored.suggested_cp_insertion is not None
            else "needs_human_review"
        ),
    )


def _mcp_candidate_hash(
    *,
    named_point: NamedPoint,
    policy: McpPolicy,
    linked_named_points: Sequence[str],
    linked_cp_candidates: Sequence[str],
) -> str:
    payload = {
        "named_point_id": named_point.named_point_id,
        "canonical_name": named_point.canonical_name,
        "point_class": list(named_point.point_class),
        "mention_page_ids": list(named_point.mention_page_ids),
        "source_families": list(named_point.source_families),
        "stale_risk": named_point.stale_risk,
        "route_position": named_point.route_position.model_dump(mode="json"),
        "terrain_risk_refs": list(named_point.terrain_risk_refs),
        "linked_named_points": list(linked_named_points),
        "linked_cp_candidates": list(linked_cp_candidates),
        "policy": policy.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_family_coverage(named_point: NamedPoint, policy: McpPolicy) -> dict[str, Any]:
    present = tuple(sorted(set(named_point.source_families)))
    missing = tuple(
        family
        for family in policy.required_source_families
        if family not in set(named_point.source_families)
    )
    return {
        "required": list(policy.required_source_families),
        "present": list(present),
        "missing_required": list(missing),
        "mandatory_complete": not missing,
    }


def _promotion_reasons(
    named_point: NamedPoint,
    *,
    nearest_scout_cp: NearestScoutCp,
    accepted_page_count: int,
    missing_required: Sequence[SourceFamily],
) -> tuple[str, ...]:
    reasons = [
        f"named point mention ratio {named_point.mention_ratio:.1%}",
        f"accepted evidence page count {accepted_page_count}",
        "route-significant MCP class: " + ", ".join(named_point.point_class),
    ]
    if nearest_scout_cp.support_found:
        reasons.append(
            f"nearby Scout CP within {nearest_scout_cp.distance_m:.1f}m"
        )
    else:
        reasons.append("no Scout CP support within policy radius")
    if named_point.terrain_risk_refs:
        reasons.append("terrain/risk evidence linked")
    if missing_required:
        reasons.append(
            "mandatory source-family gap: " + ", ".join(missing_required)
        )
    return tuple(reasons)


def _confidence_for(
    named_point: NamedPoint,
    *,
    missing_required: Sequence[SourceFamily],
    nearest_scout_cp: NearestScoutCp,
    accepted_page_count: int,
    policy: McpPolicy,
) -> Confidence:
    if (
        accepted_page_count >= policy.np_min_accepted_evidence_pages
        and named_point.mention_ratio >= policy.np_min_mention_ratio
        and not missing_required
        and nearest_scout_cp.support_found
        and named_point.route_position.coordinate_confidence != "low"
        and named_point.stale_risk != "high"
    ):
        return "high"
    if named_point.stale_risk == "high" or named_point.route_position.coordinate_confidence == "low":
        return "low" if not nearest_scout_cp.support_found else "medium"
    return "medium"


def _nearest_scout_cp(
    named_point: NamedPoint,
    checkpoints: Sequence[_ScoutCheckpoint],
    policy: McpPolicy,
) -> NearestScoutCp:
    if not checkpoints:
        existing = named_point.nearest_scout_cp
        if existing is not None:
            return existing
        return NearestScoutCp(
            candidate_id=None,
            distance_m=None,
            support_radius_m=policy.scout_cp_support_radius_m,
            support_found=False,
        )
    lat = named_point.route_position.lat
    lon = named_point.route_position.lon
    nearest = min(
        (
            (
                checkpoint,
                haversine_m(lat, lon, checkpoint.lat, checkpoint.lon),
            )
            for checkpoint in checkpoints
        ),
        key=lambda item: item[1],
    )
    return NearestScoutCp(
        candidate_id=nearest[0].candidate_id,
        distance_m=round(nearest[1], 3),
        support_radius_m=policy.scout_cp_support_radius_m,
        support_found=nearest[1] <= policy.scout_cp_support_radius_m,
    )


def _load_scout_checkpoints(project_root: Path | str | None) -> tuple[_ScoutCheckpoint, ...]:
    if project_root is None:
        return ()
    root = Path(project_root)
    project_path = root / "project.json"
    if not project_path.exists():
        return ()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    ref = project.get("checkpoint_candidates_ref")
    if not ref:
        return ()
    checkpoint_path = root / ref
    if not checkpoint_path.exists():
        return ()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    return tuple(
        _ScoutCheckpoint(
            candidate_id=item["candidate_id"],
            lat=float(item["lat"]),
            lon=float(item["lon"]),
        )
        for item in payload
        if "candidate_id" in item and "lat" in item and "lon" in item
    )


def _query_text_for_family(route_name: str, family: SourceFamily) -> str:
    return {
        "ptt_hiking": f"site:ptt.cc/bbs/Hiking {route_name} 登山",
        "hiking_biji": f"site:hiking.biji.co {route_name} 登山",
        "sunriver_culture": f"site:sunriver.com.tw {route_name} 上河 步程",
    }.get(family, f"{route_name} 登山 {family}")


def _fixture_tool_contracts(
    required_source_families: Sequence[SourceFamily],
) -> tuple[McpToolContract, ...]:
    families = tuple(required_source_families)
    return (
        McpToolContract(
            tool_id="scout.mcp.search_query_planner.fixture.v1",
            capability="search_query_planning",
            source_family_targets=families,
            input_schema_name="NamedPointEvidenceSet",
            output_schema_name="McpRetrievalPlan",
            notes=(
                "Pydantic AI（工具編排）may plan queries, but fixture tests do not call live search.",
            ),
        ),
        McpToolContract(
            tool_id="scout.mcp.web_search.fixture.v1",
            capability="web_search",
            source_family_targets=families,
            input_schema_name="McpRetrievalQuery",
            output_schema_name="McpFetchSummary",
            notes=(
                "Search results are fixture summaries; no network is performed in unit tests.",
            ),
        ),
        McpToolContract(
            tool_id="scout.mcp.fetch_summary.fixture.v1",
            capability="web_fetch_summary",
            source_family_targets=families,
            input_schema_name="McpRetrievalQuery",
            output_schema_name="McpFetchSummary",
            notes=(
                "Only short metadata/snippet hashes are stored; copyrighted payload bodies stay out of artifacts.",
            ),
        ),
        McpToolContract(
            tool_id="scout.mcp.ocr_label_normalizer.fixture.v1",
            capability="ocr_label_normalization",
            source_family_targets=("offline_map_ocr",),
            input_schema_name="NamedPointOcrLabel",
            output_schema_name="McpOcrLabel",
            notes=(
                "OCR labels keep source image hash, bbox, confidence, and remain review-required.",
            ),
        ),
    )


def _build_policy(args: argparse.Namespace) -> McpPolicy:
    return McpPolicy(
        min_spacing_m=args.min_spacing_m,
        scout_cp_support_radius_m=args.scout_cp_support_radius_m,
        np_min_mention_ratio=args.np_min_mention_ratio,
        np_min_accepted_evidence_pages=args.np_min_evidence_pages,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthesize pretrip Major Critical Point candidates from fixture-backed named point evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    search_preview_parser = subparsers.add_parser("search-preview")
    search_preview_parser.add_argument("--named-point-evidence", required=True)
    search_preview_parser.add_argument("--route-name", required=True)
    search_preview_parser.add_argument("--output-dir", required=True)
    synthesize_parser = subparsers.add_parser("synthesize")
    synthesize_parser.add_argument("--project-root", required=True)
    synthesize_parser.add_argument("--named-point-evidence", required=True)
    synthesize_parser.add_argument("--output-dir", required=True)
    synthesize_parser.add_argument("--min-spacing-m", type=float, default=1000.0)
    synthesize_parser.add_argument("--scout-cp-support-radius-m", type=float, default=250.0)
    synthesize_parser.add_argument("--np-min-mention-ratio", type=float, default=0.05)
    synthesize_parser.add_argument("--np-min-evidence-pages", type=int, default=11)
    ocr_parser = subparsers.add_parser("normalize-ocr")
    ocr_parser.add_argument("--named-point-evidence", required=True)
    ocr_parser.add_argument("--output-dir", required=True)
    support_parser = subparsers.add_parser("reconcile-support")
    support_parser.add_argument("--mcp-candidates", required=True)
    support_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    if args.command == "search-preview":
        evidence_path = Path(args.named_point_evidence)
        output_dir = Path(args.output_dir)
        plan = build_fixture_backed_retrieval_plan(
            load_named_point_evidence(evidence_path),
            route_name=args.route_name,
        )
        output_path = output_dir / DEFAULT_RETRIEVAL_PLAN_OUTPUT_NAME
        write_retrieval_plan(plan, output_path)
        print(output_path.as_posix())
        return 0
    if args.command == "synthesize":
        evidence_path = Path(args.named_point_evidence)
        output_dir = Path(args.output_dir)
        candidate_set = synthesize_mcp_candidates(
            load_named_point_evidence(evidence_path),
            project_root=Path(args.project_root),
            policy=_build_policy(args),
            source_refs=(evidence_path.as_posix(),),
        )
        output_path = output_dir / DEFAULT_OUTPUT_NAME
        write_mcp_candidate_set(candidate_set, output_path)
        print(output_path.as_posix())
        return 0
    if args.command == "reconcile-support":
        candidate_path = Path(args.mcp_candidates)
        output_dir = Path(args.output_dir)
        reconciliation = build_cp_support_reconciliation(
            load_mcp_candidate_set(candidate_path),
            source_candidate_set_ref=candidate_path.as_posix(),
        )
        output_path = output_dir / DEFAULT_CP_SUPPORT_RECONCILIATION_OUTPUT_NAME
        write_cp_support_reconciliation(reconciliation, output_path)
        print(output_path.as_posix())
        return 0
    if args.command == "normalize-ocr":
        evidence_path = Path(args.named_point_evidence)
        output_dir = Path(args.output_dir)
        label_set = normalize_ocr_labels_from_evidence(
            load_named_point_evidence(evidence_path),
            source_refs=(evidence_path.as_posix(),),
        )
        output_path = output_dir / DEFAULT_OCR_LABEL_OUTPUT_NAME
        write_ocr_label_set(label_set, output_path)
        print(output_path.as_posix())
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
