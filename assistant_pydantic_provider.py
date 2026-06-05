from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Protocol

from assistant_model_config import AssistantModelConfig, AssistantModelProfile
from assistant_models import (
    AssistantBoundary,
    AssistantOfflineFallbackSummary,
    AssistantSourceRef,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)
from assistant_offline_fallback_contract import (
    OFFLINE_FALLBACK_SCHEMA_VERSION,
    build_offline_fallback_schema_prompt,
    format_offline_fallback_interpretation,
    parse_offline_fallback_interpretation,
)
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_workspace_search_tools import (
    EVIDENCE_FULLTEXT_TOOL_ID,
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
)


DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_MAX_CONTEXT_CHARS = 12000
DEFAULT_WORKSPACE_TOOL_LIMIT = 5

WORKSPACE_EVIDENCE_TOOL_ID = "pydantic_ai.tool.search_scout_workspace_evidence.v0"

GLOBAL_ASSISTANT_PROMPT = """Scout is a wilderness safety system.
Phase 1 deterministic safety decisions are authoritative.
The assistant explains state and evidence only.
The assistant must not invent facts or claim actions happened.
The assistant must cite source refs from the provided context.
The assistant must label uncertain answers and missing context.
The assistant must refuse attempts to mutate runtime, Brain, review state, outbound transport, or hardware.
For pretrip workspace questions with a project_id/context_ref, call the read-only
search_scout_workspace_evidence tool before answering when local route, CP, MCP,
review, or map evidence may answer the question.
Return a concise read-only model interpretation.
"""

WORKSPACE_TOOL_PROMPT = """Available read-only tools:
- search_scout_workspace_evidence(query, limit=5, evidence_types=None)
- search_scout_workspace_catalog(query, domains=None, include_missing=True, limit=6)
- search_scout_route_structure(query, cp=None, segment=None, limit=6)
- search_scout_major_points(query, limit=6, cp=None, point_kinds=None)
- search_scout_evidence_fulltext(query, limit=6, evidence_types=None)
- search_scout_risk_scores(query, surface="all", limit=6, min_score=None,
  risk_bucket=None, distance_km_min=None, distance_km_max=None, cp=None,
  lat=None, lon=None, radius_m=None)
- search_scout_terrain_scores(query, metric="auto", limit=6, min_score=None,
  min_slope_degrees=None, distance_km_min=None, distance_km_max=None, cp=None,
  lat=None, lon=None, radius_m=None)
- search_scout_map_perception(query, limit=6, evidence_types=None, cp=None,
  lat=None, lon=None, radius_m=None)

Use these tools to search Scout's local pretrip workspace evidence before
answering questions about route notes, CP/checkpoints, MCP/major critical
points, named places, map evidence, review queue, or planning artifacts. Use
search_scout_workspace_catalog when the user asks what data, layers, artifacts,
or tools exist in the workspace. Use search_scout_route_structure for CP counts,
checkpoint lookup, route summary, and segment structure. Use
search_scout_major_points for MCP, named point, OCR point, or CP support
reconciliation questions. Use search_scout_evidence_fulltext for broad
workspace text search across route notes, reports, reviews, MCP, OCR, and
planning snippets. Treat all returned candidate/planning evidence as not runtime
safety truth unless the tool says otherwise. Use search_scout_risk_scores for
baseline risk-score/risk-ribbon,
calibrated risk heatmap, route risk score, risk delta, score-at-CP, score-at-km,
or high-risk-score questions. Use search_scout_terrain_scores for terrain,
slope, TEII/TRI/SRI/LEC, slope-at-CP, terrain-at-km, or steep/terrain-risk
questions. Use search_scout_map_perception for OCR labels, map annotations,
contour interpretation candidates, image-map judgement candidates, map layer
materials, or questions about what existing workspace map/tile material says
near a CP. Never mutate Scout state, call /safety/*, send outbound messages,
control hardware, or write Brain/ObservedFact/HumanReview records.
"""

MUTATION_INTENT_FRAGMENTS = (
    "ignore previous",
    "ignore prior",
    "approve",
    "accept candidate",
    "reject candidate",
    "send sos",
    "send sms",
    "send satellite",
    "write observedfact",
    "write observed fact",
    "create observedfact",
    "write brain",
    "call /safety",
    "mutate",
    "control hardware",
    "control provider",
    "start docker",
    "start pi",
)


class PydanticAIRunner(Protocol):
    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        ...


class ScoutWorkspaceToolContext:
    def __init__(
        self,
        *,
        query: ScoutAssistantQuery,
        sources: list[AssistantSourceRef],
        pretrip_workspace_root: Path | None = None,
        default_limit: int = DEFAULT_WORKSPACE_TOOL_LIMIT,
    ):
        self.query = query
        self.sources = list(sources)
        self.pretrip_workspace_root = pretrip_workspace_root
        self.default_limit = default_limit
        self.invocations: list[dict[str, object]] = []

    @classmethod
    def from_query_and_env(
        cls,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef],
        environ: dict[str, str] | None = None,
    ) -> "ScoutWorkspaceToolContext":
        resolved_environ = environ or os.environ
        root_value = resolved_environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT")
        root = Path(root_value).expanduser() if root_value else None
        return cls(query=query, sources=sources, pretrip_workspace_root=root)

    def search_scout_workspace_evidence(
        self,
        query: str,
        limit: int | None = None,
        evidence_types: list[str] | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=self.default_limit)
        project_root = self._project_root()
        if not search_text:
            result = self._tool_error("blank_query", search_text, bounded_limit)
            self.invocations.append(result)
            return result
        if project_root is None:
            result = self._tool_error("pretrip_workspace_unavailable", search_text, bounded_limit)
            self.invocations.append(result)
            return result

        try:
            from scout_agent_kb import query_project_local_evidence

            kb_result = query_project_local_evidence(
                project_root,
                query=search_text,
                limit=bounded_limit,
                evidence_types=set(evidence_types) if evidence_types else None,
            )
            result = {
                "tool_id": WORKSPACE_EVIDENCE_TOOL_ID,
                "status": "completed",
                "query": kb_result.query,
                "project_id": kb_result.project_id,
                "retrieval_engine": kb_result.retrieval_engine,
                "result_count": kb_result.result_count,
                "searched_record_count": kb_result.searched_record_count,
                "results": [_compact_tool_kb_result(item) for item in kb_result.results],
                "boundary": {
                    **kb_result.boundary.model_dump(mode="json"),
                    "read_only": True,
                    "runtime_safety_truth": False,
                    "raw_payloads_embedded": False,
                },
            }
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(type(exc).__name__, search_text, bounded_limit)
        self.invocations.append(result)
        return result

    def search_scout_workspace_catalog(
        self,
        query: str,
        domains: list[str] | None = None,
        include_missing: bool = True,
        limit: int | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=WORKSPACE_CATALOG_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_workspace_search_tools import search_project_workspace_catalog

            result = search_project_workspace_catalog(
                project_root,
                query=search_text,
                domains=domains,
                include_missing=include_missing,
                limit=bounded_limit,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=WORKSPACE_CATALOG_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_route_structure(
        self,
        query: str,
        cp: str | None = None,
        segment: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=ROUTE_STRUCTURE_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_workspace_search_tools import search_project_route_structure

            result = search_project_route_structure(
                project_root,
                query=search_text,
                cp=cp,
                segment=segment,
                limit=bounded_limit,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=ROUTE_STRUCTURE_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_major_points(
        self,
        query: str,
        limit: int | None = None,
        cp: str | None = None,
        point_kinds: list[str] | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=MAJOR_POINT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_workspace_search_tools import search_project_major_points

            result = search_project_major_points(
                project_root,
                query=search_text,
                limit=bounded_limit,
                cp=cp,
                point_kinds=point_kinds,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=MAJOR_POINT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_evidence_fulltext(
        self,
        query: str,
        limit: int | None = None,
        evidence_types: list[str] | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        if not search_text:
            result = self._tool_error(
                "blank_query",
                search_text,
                bounded_limit,
                tool_id=EVIDENCE_FULLTEXT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=EVIDENCE_FULLTEXT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_workspace_search_tools import search_project_evidence_fulltext

            result = search_project_evidence_fulltext(
                project_root,
                query=search_text,
                limit=bounded_limit,
                evidence_types=evidence_types,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=EVIDENCE_FULLTEXT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_risk_scores(
        self,
        query: str,
        surface: str = "all",
        limit: int | None = None,
        min_score: float | None = None,
        risk_bucket: str | None = None,
        distance_km_min: float | None = None,
        distance_km_max: float | None = None,
        cp: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=RISK_SCORE_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_risk_score_tool import search_project_risk_scores

            result = search_project_risk_scores(
                project_root,
                query=search_text,
                surface=surface,
                limit=bounded_limit,
                min_score=min_score,
                risk_bucket=risk_bucket,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=RISK_SCORE_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_terrain_scores(
        self,
        query: str,
        metric: str = "auto",
        limit: int | None = None,
        min_score: float | None = None,
        min_slope_degrees: float | None = None,
        distance_km_min: float | None = None,
        distance_km_max: float | None = None,
        cp: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=TERRAIN_SCORE_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_terrain_score_tool import search_project_terrain_scores

            result = search_project_terrain_scores(
                project_root,
                query=search_text,
                metric=metric,
                limit=bounded_limit,
                min_score=min_score,
                min_slope_degrees=min_slope_degrees,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=TERRAIN_SCORE_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_map_perception(
        self,
        query: str,
        limit: int | None = None,
        evidence_types: list[str] | None = None,
        cp: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=MAP_PERCEPTION_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            from scout_map_perception_tool import search_project_map_perception

            result = search_project_map_perception(
                project_root,
                query=search_text,
                limit=bounded_limit,
                evidence_types=evidence_types,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=MAP_PERCEPTION_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def tool_source_ref(self, tool_id: str | None = None) -> AssistantSourceRef | None:
        invocations = [
            invocation
            for invocation in self.invocations
            if tool_id is None or invocation.get("tool_id") == tool_id
        ]
        if not invocations:
            return None
        latest = invocations[-1]
        latest_tool_id = str(latest.get("tool_id") or WORKSPACE_EVIDENCE_TOOL_ID)
        if latest_tool_id == RISK_SCORE_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_risk_scores"
            evidence_type = "assistant_risk_score_tool_invocation"
        elif latest_tool_id == TERRAIN_SCORE_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_terrain_scores"
            evidence_type = "assistant_terrain_score_tool_invocation"
        elif latest_tool_id == MAP_PERCEPTION_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_map_perception"
            evidence_type = "assistant_map_perception_tool_invocation"
        elif latest_tool_id == WORKSPACE_CATALOG_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_workspace_catalog"
            evidence_type = "assistant_workspace_catalog_tool_invocation"
        elif latest_tool_id == ROUTE_STRUCTURE_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_route_structure"
            evidence_type = "assistant_route_structure_tool_invocation"
        elif latest_tool_id == MAJOR_POINT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_major_points"
            evidence_type = "assistant_major_point_tool_invocation"
        elif latest_tool_id == EVIDENCE_FULLTEXT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_evidence_fulltext"
            evidence_type = "assistant_evidence_fulltext_tool_invocation"
        else:
            source_path = "assistant_pydantic_provider.search_scout_workspace_evidence"
            evidence_type = "assistant_workspace_tool_invocation"
        return AssistantSourceRef(
            source_id=latest_tool_id,
            source_path=source_path,
            evidence_type=evidence_type,
            selected=True,
            context_summary={
                "tool_id": latest_tool_id,
                "invocation_count": len(invocations),
                "latest": latest,
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )

    def tool_source_refs(self) -> list[AssistantSourceRef]:
        refs = []
        for tool_id in _dedupe_preserving_order(
            [
                str(invocation.get("tool_id") or WORKSPACE_EVIDENCE_TOOL_ID)
                for invocation in self.invocations
            ]
        ):
            ref = self.tool_source_ref(tool_id=tool_id)
            if ref is not None:
                refs.append(ref)
        return refs

    def _project_root(self) -> Path | None:
        if self.query.surface.value != "pretrip" or self.pretrip_workspace_root is None:
            return None
        project_id = self.query.project_id or self.query.context_ref
        if not project_id:
            return None
        candidate = self.pretrip_workspace_root / project_id
        if (candidate / "project.json").exists():
            return candidate
        return None

    def _tool_error(
        self,
        error_type: str,
        query: str,
        limit: int,
        *,
        tool_id: str = WORKSPACE_EVIDENCE_TOOL_ID,
    ) -> dict[str, object]:
        return {
            "tool_id": tool_id,
            "status": "failed",
            "error_type": error_type,
            "query": query,
            "limit": limit,
            "project_id": self.query.project_id or self.query.context_ref,
            "results": [],
            "boundary": {
                "read_only": True,
                "offline_only": True,
                "local_evidence_only": True,
                "runtime_safety_truth": False,
                "live_safety_api_calls_allowed": False,
                "phase1_safety_mutation_allowed": False,
                "remote_outbound_send_allowed": False,
                "hardware_control_allowed": False,
                "raw_payloads_embedded": False,
            },
        }


def augment_sources_with_workspace_evidence_tool(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    environ: dict[str, str] | None = None,
    limit: int = DEFAULT_WORKSPACE_TOOL_LIMIT,
) -> list[AssistantSourceRef]:
    augmented = list(sources)
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(
        query,
        sources=sources,
        environ=environ,
    )
    if _looks_like_workspace_catalog_query(query.question) and not any(
        source.source_id == WORKSPACE_CATALOG_TOOL_ID for source in augmented
    ):
        catalog_result = tool_context.search_scout_workspace_catalog(
            query=query.question,
            limit=limit,
        )
        if catalog_result.get("status") == "completed":
            catalog_source = tool_context.tool_source_ref(tool_id=WORKSPACE_CATALOG_TOOL_ID)
            if catalog_source is not None:
                augmented = [catalog_source, *augmented]

    if _looks_like_route_structure_query(query.question) and not any(
        source.source_id == ROUTE_STRUCTURE_TOOL_ID for source in augmented
    ):
        route_result = tool_context.search_scout_route_structure(
            query=query.question,
            limit=limit,
        )
        if route_result.get("status") == "completed":
            route_source = tool_context.tool_source_ref(tool_id=ROUTE_STRUCTURE_TOOL_ID)
            if route_source is not None:
                augmented = [route_source, *augmented]

    if _looks_like_major_point_query(query.question) and not any(
        source.source_id == MAJOR_POINT_TOOL_ID for source in augmented
    ):
        major_result = tool_context.search_scout_major_points(
            query=query.question,
            limit=limit,
        )
        if major_result.get("status") == "completed":
            major_source = tool_context.tool_source_ref(tool_id=MAJOR_POINT_TOOL_ID)
            if major_source is not None:
                augmented = [major_source, *augmented]

    if _looks_like_evidence_fulltext_query(query.question) and not any(
        source.source_id == EVIDENCE_FULLTEXT_TOOL_ID for source in augmented
    ):
        fulltext_result = tool_context.search_scout_evidence_fulltext(
            query=query.question,
            limit=limit,
        )
        if fulltext_result.get("status") == "completed":
            fulltext_source = tool_context.tool_source_ref(tool_id=EVIDENCE_FULLTEXT_TOOL_ID)
            if fulltext_source is not None:
                augmented = [fulltext_source, *augmented]

    if _looks_like_risk_score_query(query.question) and not any(
        source.source_id == RISK_SCORE_TOOL_ID for source in augmented
    ):
        risk_result = tool_context.search_scout_risk_scores(
            query=query.question,
            limit=limit,
        )
        if risk_result.get("status") == "completed":
            risk_source = tool_context.tool_source_ref(tool_id=RISK_SCORE_TOOL_ID)
            if risk_source is not None:
                augmented = [risk_source, *augmented]

    if _looks_like_terrain_score_query(query.question) and not any(
        source.source_id == TERRAIN_SCORE_TOOL_ID for source in augmented
    ):
        terrain_result = tool_context.search_scout_terrain_scores(
            query=query.question,
            limit=limit,
        )
        if terrain_result.get("status") == "completed":
            terrain_source = tool_context.tool_source_ref(tool_id=TERRAIN_SCORE_TOOL_ID)
            if terrain_source is not None:
                risk_sources = [
                    source for source in augmented if source.source_id == RISK_SCORE_TOOL_ID
                ]
                other_sources = [
                    source for source in augmented if source.source_id != RISK_SCORE_TOOL_ID
                ]
                augmented = [*risk_sources, terrain_source, *other_sources]

    if _looks_like_map_perception_query(query.question) and not any(
        source.source_id == MAP_PERCEPTION_TOOL_ID for source in augmented
    ):
        map_result = tool_context.search_scout_map_perception(
            query=query.question,
            limit=limit,
        )
        if map_result.get("status") == "completed":
            map_source = tool_context.tool_source_ref(tool_id=MAP_PERCEPTION_TOOL_ID)
            if map_source is not None:
                priority_sources = [
                    source
                    for source in augmented
                    if source.source_id in {RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID}
                ]
                other_sources = [
                    source
                    for source in augmented
                    if source.source_id not in {RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID}
                ]
                augmented = [*priority_sources, map_source, *other_sources]

    if not any(source.source_id == WORKSPACE_EVIDENCE_TOOL_ID for source in augmented):
        result = tool_context.search_scout_workspace_evidence(
            query=query.question,
            limit=limit,
        )
        if result.get("status") == "completed":
            tool_source = tool_context.tool_source_ref(tool_id=WORKSPACE_EVIDENCE_TOOL_ID)
            if tool_source is not None:
                risk_sources = [
                    source for source in augmented if source.source_id == RISK_SCORE_TOOL_ID
                ]
                terrain_sources = [
                    source for source in augmented if source.source_id == TERRAIN_SCORE_TOOL_ID
                ]
                map_sources = [
                    source for source in augmented if source.source_id == MAP_PERCEPTION_TOOL_ID
                ]
                structured_sources = [
                    source
                    for source in augmented
                    if source.source_id
                    in {
                        WORKSPACE_CATALOG_TOOL_ID,
                        ROUTE_STRUCTURE_TOOL_ID,
                        MAJOR_POINT_TOOL_ID,
                        EVIDENCE_FULLTEXT_TOOL_ID,
                    }
                ]
                other_sources = [
                    source
                    for source in augmented
                    if source.source_id
                    not in {
                        RISK_SCORE_TOOL_ID,
                        TERRAIN_SCORE_TOOL_ID,
                        MAP_PERCEPTION_TOOL_ID,
                        WORKSPACE_CATALOG_TOOL_ID,
                        ROUTE_STRUCTURE_TOOL_ID,
                        MAJOR_POINT_TOOL_ID,
                        EVIDENCE_FULLTEXT_TOOL_ID,
                    }
                ]
                augmented = [
                    *structured_sources,
                    *risk_sources,
                    *terrain_sources,
                    *map_sources,
                    tool_source,
                    *other_sources,
                ]
    return augmented


def build_workspace_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    risk_response = _build_risk_score_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if risk_response is not None:
        return risk_response
    terrain_response = _build_terrain_score_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if terrain_response is not None:
        return terrain_response
    map_response = _build_map_perception_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if map_response is not None:
        return map_response
    structured_response = _build_structured_workspace_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if structured_response is not None:
        return structured_response
    tool_source = _first_workspace_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    top_results = [item for item in results[:3] if isinstance(item, dict)]
    if not top_results:
        return None

    evidence_lines = []
    for item in top_results:
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("evidence_type"),
                    item.get("record_id"),
                    item.get("snippet"),
                )
                if part
            )
        )
    answer = (
        "Scout AI workspace evidence tool fallback: Pydantic AI provider was unavailable, "
        "so this read-only answer uses the workspace evidence tool result. "
        f"Question: {query.question}. "
        f"Retrieval engine: {latest.get('retrieval_engine')}. "
        f"Top evidence: {'; '.join(evidence_lines)}. "
        "These are candidate/planning evidence snippets, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={WORKSPACE_EVIDENCE_TOOL_ID}",
            "Workspace evidence tool fallback summarized bounded read-only search snippets after provider failure.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _build_risk_score_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_source = _first_risk_score_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    evidence_lines = []
    for item in [item for item in results[:5] if isinstance(item, dict)]:
        distance = item.get("distance_km")
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("surface"),
                    f"score={item.get('score')}",
                    item.get("risk_bucket"),
                    f"km={distance}" if distance is not None else None,
                    f"delta={item.get('calibration_delta')}"
                    if item.get("calibration_delta") is not None
                    else None,
                    f"lat={item.get('lat')},lon={item.get('lon')}"
                    if item.get("lat") is not None and item.get("lon") is not None
                    else None,
                )
                if part
            )
        )
    summaries = latest.get("summaries") if isinstance(latest.get("summaries"), dict) else {}
    answer = (
        "Scout AI risk score tool fallback: this read-only answer uses the route "
        "risk score tool result. "
        f"Question: {query.question}. "
        f"Matched score count: {latest.get('matched_score_count')}; "
        f"searched score count: {latest.get('searched_score_count')}. "
        f"Surface summaries: {json.dumps(summaries, ensure_ascii=False, sort_keys=True)[:900]}. "
        f"Top scores: {'; '.join(evidence_lines)}. "
        "These are pretrip candidate score layers, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={RISK_SCORE_TOOL_ID}",
            "Risk score tool fallback summarized bounded read-only score layer results.",
            "Baseline/calibration risk scores were not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _build_terrain_score_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_source = _first_terrain_score_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    evidence_lines = []
    for item in [item for item in results[:5] if isinstance(item, dict)]:
        distance = item.get("distance_km")
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("metric"),
                    f"{item.get('score_field')}={item.get('score')}",
                    item.get("slope_measurement_status"),
                    f"km={distance}" if distance is not None else None,
                    f"lat={item.get('lat')},lon={item.get('lon')}"
                    if item.get("lat") is not None and item.get("lon") is not None
                    else None,
                )
                if part
            )
        )
    summaries = latest.get("summaries") if isinstance(latest.get("summaries"), dict) else {}
    answer = (
        "Scout AI terrain score tool fallback: this read-only answer uses the "
        "route terrain/slope score tool result. "
        f"Question: {query.question}. "
        f"Matched sample count: {latest.get('matched_sample_count')}; "
        f"searched sample count: {latest.get('searched_sample_count')}. "
        f"Metric: {latest.get('metric')}. "
        f"Terrain summaries: {json.dumps(summaries, ensure_ascii=False, sort_keys=True)[:900]}. "
        f"Top terrain samples: {'; '.join(evidence_lines)}. "
        "These are pretrip candidate terrain layers, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={TERRAIN_SCORE_TOOL_ID}",
            "Terrain score tool fallback summarized bounded read-only terrain layer results.",
            "Terrain/slope scores were not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _build_map_perception_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_source = _first_map_perception_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    evidence_lines = []
    for item in [item for item in results[:5] if isinstance(item, dict)]:
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("evidence_type"),
                    item.get("label_text") or item.get("candidate_id") or item.get("layer_id"),
                    f"cp={','.join(item.get('checkpoint_refs', []))}"
                    if isinstance(item.get("checkpoint_refs"), list)
                    else None,
                    f"source={item.get('source_ref') or item.get('source_path')}",
                    f"lat={item.get('lat')},lon={item.get('lon')}"
                    if item.get("lat") is not None and item.get("lon") is not None
                    else None,
                )
                if part
            )
        )
    summaries = latest.get("summaries") if isinstance(latest.get("summaries"), dict) else {}
    answer = (
        "Scout AI map perception tool fallback: this read-only answer uses "
        "existing workspace map/tile perception materials. "
        f"Question: {query.question}. "
        f"Matched material count: {latest.get('matched_material_count')}; "
        f"searched material count: {latest.get('searched_material_count')}. "
        f"Summaries: {json.dumps(summaries, ensure_ascii=False, sort_keys=True)[:900]}. "
        f"Top materials: {'; '.join(evidence_lines)}. "
        "These are OCR/contour/map-layer candidate materials, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={MAP_PERCEPTION_TOOL_ID}",
            "Map perception tool fallback summarized bounded read-only workspace materials.",
            "OCR, image-map, contour, and map-layer candidates were not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _build_structured_workspace_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    for tool_id, label in (
        (WORKSPACE_CATALOG_TOOL_ID, "workspace catalog"),
        (ROUTE_STRUCTURE_TOOL_ID, "route structure"),
        (MAJOR_POINT_TOOL_ID, "major point"),
        (EVIDENCE_FULLTEXT_TOOL_ID, "evidence full-text"),
    ):
        tool_source = _first_tool_source_by_id(sources, tool_id)
        if tool_source is None:
            continue
        summary = tool_source.context_summary or {}
        latest = summary.get("latest")
        if not isinstance(latest, dict) or latest.get("status") != "completed":
            continue
        evidence_lines = _generic_tool_evidence_lines(latest)
        if not evidence_lines:
            continue
        summaries = latest.get("summaries") if isinstance(latest.get("summaries"), dict) else {}
        answer = (
            f"Scout AI {label} tool fallback: this read-only answer uses "
            "structured local workspace evidence. "
            f"Question: {query.question}. "
            f"Result count: {latest.get('result_count')}. "
            f"Summaries: {json.dumps(summaries, ensure_ascii=False, sort_keys=True)[:900]}. "
            f"Top evidence: {'; '.join(evidence_lines)}. "
            "These are local planning/debug evidence, not runtime safety truth."
        )
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=answer,
            sources=sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=[
                f"provider_error_type={provider_error_type}",
                f"resolved_by={tool_id}",
                f"{label} tool fallback summarized bounded read-only workspace results.",
                "Candidate/debug/planning evidence was not promoted to runtime safety truth.",
                "No runtime, Brain, review, outbound, or hardware state was changed.",
            ],
        )
    return None


def _generic_tool_evidence_lines(latest: dict[str, object]) -> list[str]:
    results = latest.get("results")
    if not isinstance(results, list):
        return []
    lines = []
    for item in [item for item in results[:5] if isinstance(item, dict)]:
        parts = (
            item.get("evidence_type") or item.get("domain"),
            item.get("candidate_id") or item.get("record_id") or item.get("ref_key"),
            item.get("label") or item.get("title") or item.get("source_path"),
            item.get("snippet"),
            f"cp={item.get('nearest_cp_candidate_id')}"
            if item.get("nearest_cp_candidate_id") is not None
            else None,
            f"count={item.get('count_keys')}" if item.get("count_keys") else None,
        )
        line = " | ".join(str(part) for part in parts if part)
        if line:
            lines.append(line)
    return lines


def _tool_result_response_for_unresolved_model_output(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    model_output: str,
) -> ScoutAssistantResponse | None:
    if not _looks_like_unresolved_tool_call(model_output):
        return None
    risk_response = _build_risk_score_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type="UnresolvedToolCallText",
    )
    if risk_response is None:
        terrain_response = _build_terrain_score_tool_fallback_response(
            query,
            sources=sources,
            provider_error_type="UnresolvedToolCallText",
        )
        if terrain_response is None:
            map_response = _build_map_perception_tool_fallback_response(
                query,
                sources=sources,
                provider_error_type="UnresolvedToolCallText",
            )
            if map_response is None:
                structured_response = _build_structured_workspace_tool_fallback_response(
                    query,
                    sources=sources,
                    provider_error_type="UnresolvedToolCallText",
                )
                if structured_response is None:
                    return None
                return structured_response.model_copy(
                    update={
                        "limitations": [
                            *structured_response.limitations,
                            "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
                        ]
                    }
                )
            return map_response.model_copy(
                update={
                    "limitations": [
                        *map_response.limitations,
                        "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
                    ]
                }
            )
        return terrain_response.model_copy(
            update={
                "limitations": [
                    *terrain_response.limitations,
                    "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
                ]
            }
        )
    return risk_response.model_copy(
        update={
            "limitations": [
                *risk_response.limitations,
                "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
            ]
        }
    )


def _looks_like_unresolved_tool_call(model_output: str) -> bool:
    stripped = str(model_output or "").strip()
    if "tool_code" in stripped and "search_scout_" in stripped:
        return True
    if "search_scout_" in stripped and stripped.startswith("```"):
        return True
    if stripped.startswith("[search_scout_") or stripped.startswith("search_scout_"):
        return True
    return False


def create_configured_pydantic_runner(
    config: AssistantModelConfig,
    *,
    environ: dict[str, str] | None = None,
) -> PydanticAIRunner:
    cloud_runner = PydanticAIEnvRunner.from_profile(
        config.cloud_model,
        environ=environ,
    )
    if config.active_profile == "local":
        return PydanticAIEnvRunner.from_profile(
            config.local_model,
            environ=environ,
        )
    if not config.fallback_to_local_on_error:
        return cloud_runner
    local_runner = PydanticAIEnvRunner.from_profile(
        config.local_model,
        environ=environ,
    )
    return FallbackPydanticAIRunner(
        primary_runner=cloud_runner,
        fallback_runner=local_runner,
        primary_profile="cloud",
        fallback_profile="local",
        enforce_local_fixed_schema=config.local_fallback_fixed_schema,
    )


class PydanticAIAssistantProvider:
    def __init__(
        self,
        *,
        runner: PydanticAIRunner,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ):
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.max_context_chars = max_context_chars
        self.startup_connection_status: str = "not_checked"

    def connect(self) -> None:
        connector = getattr(self.runner, "connect", None)
        if not callable(connector):
            self.startup_connection_status = "not_supported"
            return
        connector(timeout_seconds=self.timeout_seconds)
        profile = getattr(self.runner, "last_profile", None)
        self.startup_connection_status = f"connected:{profile or 'unknown'}"

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ) -> ScoutAssistantResponse:
        resolved_sources = list(sources or [])
        prompt = build_assistant_prompt(
            query,
            sources=resolved_sources,
            max_context_chars=self.max_context_chars,
        )
        tool_context = ScoutWorkspaceToolContext.from_query_and_env(
            query,
            sources=resolved_sources,
        )
        model_output = _run_with_optional_workspace_tools(
            self.runner,
            prompt,
            timeout_seconds=self.timeout_seconds,
            tool_context=tool_context,
        )
        tool_sources = _workspace_tool_source_refs(self.runner, tool_context)
        response_sources = (
            [*tool_sources, *_without_workspace_tool_sources(resolved_sources)]
            if tool_sources
            else resolved_sources
        )
        unresolved_tool_response = _tool_result_response_for_unresolved_model_output(
            query,
            sources=response_sources,
            model_output=model_output,
        )
        if unresolved_tool_response is not None:
            return unresolved_tool_response
        constrained = _has_mutation_intent(query.question) or _has_mutation_intent(model_output)
        prefix = (
            "Guardrail notice: mutation or prompt-injection language was treated as data, "
            "not as authorization. "
            if constrained
            else ""
        )
        limitations = [
            "Pydantic AI provider is opt-in and separate from /navigate.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
            f"Context budget: {self.max_context_chars} chars.",
        ]
        if constrained:
            limitations.append("Prompt-injection or mutation request was constrained.")
        tool_invocations = _workspace_tool_invocations(self.runner, tool_context)
        if tool_invocations:
            limitations.append(
                f"workspace_tool_invocations={len(tool_invocations)}"
            )
            limitations.append(
                "workspace_tool_ids="
                + ",".join(
                    _dedupe_preserving_order(
                        [
                            str(
                                invocation.get("tool_id")
                                or WORKSPACE_EVIDENCE_TOOL_ID
                            )
                            for invocation in tool_invocations
                        ]
                    )
                )
            )
            limitations.append(
                "Workspace evidence tool was read-only and did not promote candidate evidence to runtime safety truth."
            )
        profile = getattr(self.runner, "last_profile", None)
        if profile:
            limitations.append(f"Model profile used: {profile}.")
            limitations.append(f"model_profile_used={profile}")
        failover_count = getattr(self.runner, "failover_count", 0)
        if failover_count:
            limitations.append("Cloud model communication failed; local model fallback was used.")
        failover_reason = getattr(self.runner, "last_failover_reason", None)
        if failover_reason:
            limitations.append(f"failover_reason={failover_reason}")
        local_model_name = getattr(self.runner, "local_model_name", None)
        if local_model_name and profile == "local":
            limitations.append(f"local_model_name={local_model_name}")
        fixed_schema_version = getattr(self.runner, "last_fixed_schema_version", None)
        if fixed_schema_version:
            limitations.append(
                f"fixed_schema_offline_fallback_contract={fixed_schema_version}"
            )
        offline_fallback_payload = getattr(
            self.runner,
            "last_offline_fallback_interpretation",
            None,
        )
        offline_fallback = (
            AssistantOfflineFallbackSummary.model_validate(offline_fallback_payload)
            if offline_fallback_payload
            else None
        )
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=f"{prefix}Pydantic AI read-only model interpretation: {str(model_output).strip()}",
            sources=response_sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=limitations,
            offline_fallback=offline_fallback,
        )


class FallbackPydanticAIRunner:
    def __init__(
        self,
        *,
        primary_runner: PydanticAIRunner,
        fallback_runner: PydanticAIRunner,
        primary_profile: str = "cloud",
        fallback_profile: str = "local",
        max_fallback_concurrency: int = 1,
        enforce_local_fixed_schema: bool = False,
    ):
        self.primary_runner = primary_runner
        self.fallback_runner = fallback_runner
        self.primary_profile = primary_profile
        self.fallback_profile = fallback_profile
        self.last_profile: str | None = None
        self.last_error_type: str | None = None
        self.last_failover_reason: str | None = None
        self.local_model_name: str | None = getattr(fallback_runner, "model_name", None)
        self.max_fallback_concurrency = max(1, max_fallback_concurrency)
        self.enforce_local_fixed_schema = enforce_local_fixed_schema
        self.fixed_schema_offline_fallback_contract = (
            OFFLINE_FALLBACK_SCHEMA_VERSION if enforce_local_fixed_schema else None
        )
        self.last_fixed_schema_version: str | None = None
        self.last_offline_fallback_interpretation: dict[str, object] | None = None
        self.last_workspace_tool_invocations: list[dict[str, object]] = []
        self._fallback_semaphore = threading.BoundedSemaphore(self.max_fallback_concurrency)
        self.failover_count = 0

    def connect(self, *, timeout_seconds: int) -> None:
        try:
            _connect_runner(self.primary_runner, timeout_seconds=timeout_seconds)
            self.last_profile = self.primary_profile
            return
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"primary_connect_error:{type(exc).__name__}"
            self.failover_count += 1
        try:
            self.last_profile = self.fallback_profile
            _connect_runner(self.fallback_runner, timeout_seconds=timeout_seconds)
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"local_connect_error:{type(exc).__name__}"
            raise

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        try:
            result = self.primary_runner.run(prompt, timeout_seconds=timeout_seconds)
            self.last_profile = self.primary_profile
            self.last_fixed_schema_version = None
            self.last_offline_fallback_interpretation = None
            self.last_workspace_tool_invocations = []
            return result
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"primary_run_error:{type(exc).__name__}"
            self.failover_count += 1
            return self._run_fallback_with_optional_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=None,
            )

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        try:
            result = _run_with_optional_workspace_tools(
                self.primary_runner,
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
            self.last_profile = self.primary_profile
            self.last_fixed_schema_version = None
            self.last_offline_fallback_interpretation = None
            self.last_workspace_tool_invocations = list(tool_context.invocations)
            return result
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"primary_run_error:{type(exc).__name__}"
            self.failover_count += 1
            return self._run_fallback_with_optional_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )

    def _run_fallback_with_optional_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext | None,
    ) -> str:
        acquired = self._fallback_semaphore.acquire(blocking=False)
        if not acquired:
            self.last_profile = self.fallback_profile
            self.last_error_type = "LocalFallbackBusy"
            self.last_failover_reason = "local_busy:discard_stale_request"
            raise RuntimeError("local fallback busy; stale model request discarded")
        try:
            self.last_profile = self.fallback_profile
            fallback_prompt = (
                build_offline_fallback_schema_prompt(
                    prompt,
                    local_model_name=self.local_model_name,
                )
                if self.enforce_local_fixed_schema
                else prompt
            )
            raw_output = _run_with_optional_workspace_tools(
                self.fallback_runner,
                fallback_prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
            self.last_workspace_tool_invocations = (
                list(tool_context.invocations) if tool_context is not None else []
            )
            if not self.enforce_local_fixed_schema:
                self.last_fixed_schema_version = None
                self.last_offline_fallback_interpretation = None
                return raw_output
            try:
                interpretation = parse_offline_fallback_interpretation(raw_output)
            except Exception as exc:
                self.last_error_type = type(exc).__name__
                self.last_failover_reason = (
                    f"local_schema_validation_error:{type(exc).__name__}"
                )
                raise
            self.last_fixed_schema_version = interpretation.schema_version
            self.last_offline_fallback_interpretation = interpretation.model_dump(
                mode="json"
            )
            return format_offline_fallback_interpretation(interpretation)
        except Exception as exc:
            if not str(self.last_failover_reason or "").startswith(
                "local_schema_validation_error:"
            ):
                self.last_error_type = type(exc).__name__
                self.last_failover_reason = f"local_run_error:{type(exc).__name__}"
            raise
        finally:
            self._fallback_semaphore.release()


class PydanticAIEnvRunner:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        base_url: str | None = None,
        token_id: str | None = None,
        token_env_var: str | None = None,
        api_key: str | None = None,
        profile_name: str | None = None,
    ):
        self.model_name = model_name or os.getenv(
            "SCOUT_AI_ASSISTANT_MODEL",
            "google/gemma-4-31b-it",
        )
        self.base_url = base_url
        self.token_id = token_id
        self.token_env_var = token_env_var
        self.api_key = api_key
        self.profile_name = profile_name
        self.last_workspace_tool_invocations: list[dict[str, object]] = []

    @classmethod
    def from_profile(
        cls,
        profile: AssistantModelProfile,
        *,
        environ: dict[str, str] | None = None,
    ) -> "PydanticAIEnvRunner":
        resolved_environ = environ or os.environ
        return cls(
            model_name=profile.model_name,
            base_url=profile.base_url,
            token_id=profile.token_id,
            token_env_var=profile.token_env_var,
            api_key=(
                resolved_environ.get(profile.token_env_var)
                if profile.token_env_var
                else None
            ),
            profile_name=profile.profile,
        )

    def connect(self, *, timeout_seconds: int) -> None:
        self.run(
            "Scout assistant connectivity check. Reply with OK.",
            timeout_seconds=timeout_seconds,
        )

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._run_model, prompt)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("pydantic assistant provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._run_model_with_workspace_tools, prompt, tool_context)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("pydantic assistant provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_model(self, prompt: str) -> str:
        from pydantic_ai import Agent
        try:
            from pydantic_ai.models.openai import OpenAIChatModel
        except ImportError:  # pragma: no cover - compatibility with older pydantic-ai.
            from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(base_url=self.base_url, api_key=self.api_key)
        agent = Agent(
            OpenAIChatModel(self.model_name, provider=provider),
            system_prompt=GLOBAL_ASSISTANT_PROMPT,
        )
        result = agent.run_sync(prompt, model_settings={"max_tokens": 512})
        return str(getattr(result, "output", getattr(result, "data", result)))

    def _run_model_with_workspace_tools(
        self,
        prompt: str,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        from pydantic_ai import Agent
        try:
            from pydantic_ai.models.openai import OpenAIChatModel
        except ImportError:  # pragma: no cover - compatibility with older pydantic-ai.
            from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(base_url=self.base_url, api_key=self.api_key)
        agent = Agent(
            OpenAIChatModel(self.model_name, provider=provider),
            system_prompt=f"{GLOBAL_ASSISTANT_PROMPT}\n{WORKSPACE_TOOL_PROMPT}",
        )

        @agent.tool_plain(
            name="search_scout_workspace_evidence",
            description=(
                "Search Scout's local pretrip workspace evidence. This tool is read-only, "
                "offline/local-evidence only, and never mutates runtime safety state."
            ),
        )
        def search_scout_workspace_evidence(
            query: str,
            limit: int = DEFAULT_WORKSPACE_TOOL_LIMIT,
            evidence_types: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_workspace_evidence(
                query=query,
                limit=limit,
                evidence_types=evidence_types,
            )

        @agent.tool_plain(
            name="search_scout_workspace_catalog",
            description=(
                "List and search Scout pretrip workspace artifact refs, data "
                "families, source paths, counts, and missing layers. This tool is "
                "read-only and never mutates runtime safety state."
            ),
        )
        def search_scout_workspace_catalog(
            query: str,
            domains: list[str] | None = None,
            include_missing: bool = True,
            limit: int = 6,
        ) -> dict[str, object]:
            return tool_context.search_scout_workspace_catalog(
                query=query,
                domains=domains,
                include_missing=include_missing,
                limit=limit,
            )

        @agent.tool_plain(
            name="search_scout_route_structure",
            description=(
                "Search Scout's route summary, checkpoint candidates, and segment "
                "candidates. Use for CP counts, CP lookup, route distance, and "
                "segment structure. This tool is read-only."
            ),
        )
        def search_scout_route_structure(
            query: str,
            cp: str | None = None,
            segment: str | None = None,
            limit: int = 6,
        ) -> dict[str, object]:
            return tool_context.search_scout_route_structure(
                query=query,
                cp=cp,
                segment=segment,
                limit=limit,
            )

        @agent.tool_plain(
            name="search_scout_major_points",
            description=(
                "Search MCP/major critical point candidates, named points, OCR "
                "labels, and CP support reconciliation. Use for named places such "
                "as 黑水塘 and questions about which CP a point is near."
            ),
        )
        def search_scout_major_points(
            query: str,
            limit: int = 6,
            cp: str | None = None,
            point_kinds: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_major_points(
                query=query,
                limit=limit,
                cp=cp,
                point_kinds=point_kinds,
            )

        @agent.tool_plain(
            name="search_scout_evidence_fulltext",
            description=(
                "Run broad full-text search over Scout's local evidence index, "
                "including route notes, reports, reviews, MCP, OCR, and planning "
                "snippets. This tool is read-only and source-backed."
            ),
        )
        def search_scout_evidence_fulltext(
            query: str,
            limit: int = 6,
            evidence_types: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_evidence_fulltext(
                query=query,
                limit=limit,
                evidence_types=evidence_types,
            )

        @agent.tool_plain(
            name="search_scout_risk_scores",
            description=(
                "Search Scout's baseline risk score/ribbon and calibrated risk heatmap "
                "score layers. This tool is read-only and returns bounded candidate "
                "score summaries with route distance, coordinate, bucket, and deltas."
            ),
        )
        def search_scout_risk_scores(
            query: str,
            surface: str = "all",
            limit: int = 6,
            min_score: float | None = None,
            risk_bucket: str | None = None,
            distance_km_min: float | None = None,
            distance_km_max: float | None = None,
            cp: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            radius_m: float | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_risk_scores(
                query=query,
                surface=surface,
                limit=limit,
                min_score=min_score,
                risk_bucket=risk_bucket,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            )

        @agent.tool_plain(
            name="search_scout_terrain_scores",
            description=(
                "Search Scout's route-aligned terrain/slope score layers, including "
                "direct slope fields when present and TEII/TRI/SRI/LEC terrain "
                "dimensions. This tool is read-only and returns bounded candidate "
                "terrain summaries with route distance and coordinate."
            ),
        )
        def search_scout_terrain_scores(
            query: str,
            metric: str = "auto",
            limit: int = 6,
            min_score: float | None = None,
            min_slope_degrees: float | None = None,
            distance_km_min: float | None = None,
            distance_km_max: float | None = None,
            cp: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            radius_m: float | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_terrain_scores(
                query=query,
                metric=metric,
                limit=limit,
                min_score=min_score,
                min_slope_degrees=min_slope_degrees,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            )

        @agent.tool_plain(
            name="search_scout_map_perception",
            description=(
                "Search Scout's existing workspace map/tile perception materials, "
                "including OCR labels, contour interpretation candidates, named-point "
                "OCR context, and map layer/source refs. This tool is read-only and "
                "does not run new OCR or vision inference."
            ),
        )
        def search_scout_map_perception(
            query: str,
            limit: int = 6,
            evidence_types: list[str] | None = None,
            cp: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            radius_m: float | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_map_perception(
                query=query,
                limit=limit,
                evidence_types=evidence_types,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            )

        tool_prompt = f"{WORKSPACE_TOOL_PROMPT}\n{prompt}"
        result = agent.run_sync(tool_prompt, model_settings={"max_tokens": 768})
        self.last_workspace_tool_invocations = list(tool_context.invocations)
        return str(getattr(result, "output", getattr(result, "data", result)))


def build_assistant_prompt(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    context = {
        "surface": query.surface.value,
        "question": query.question,
        "context_ref": query.context_ref,
        "selected_event_id": query.selected_event_id,
        "selected_artifact_id": query.selected_artifact_id,
        "project_id": query.project_id,
        "sources": [source.model_dump(mode="json") for source in sources],
    }
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if len(context_json) > max_context_chars:
        context_json = f"{context_json[:max_context_chars]}\n[context truncated]"
    return f"{GLOBAL_ASSISTANT_PROMPT}\nContext:\n{context_json}\n"


def _has_mutation_intent(text: str) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in MUTATION_INTENT_FRAGMENTS)


def _run_with_optional_workspace_tools(
    runner: PydanticAIRunner,
    prompt: str,
    *,
    timeout_seconds: int,
    tool_context: ScoutWorkspaceToolContext | None,
) -> str:
    if tool_context is not None:
        runner_with_tools = getattr(runner, "run_with_workspace_tools", None)
        if callable(runner_with_tools):
            return runner_with_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
    return runner.run(prompt, timeout_seconds=timeout_seconds)


def _workspace_tool_invocations(
    runner: PydanticAIRunner,
    tool_context: ScoutWorkspaceToolContext,
) -> list[dict[str, object]]:
    runner_invocations = getattr(runner, "last_workspace_tool_invocations", None)
    if isinstance(runner_invocations, list):
        return [item for item in runner_invocations if isinstance(item, dict)]
    return list(tool_context.invocations)


def _workspace_tool_source_refs(
    runner: PydanticAIRunner,
    tool_context: ScoutWorkspaceToolContext,
) -> list[AssistantSourceRef]:
    invocations = _workspace_tool_invocations(runner, tool_context)
    if not invocations:
        return []
    context = ScoutWorkspaceToolContext(
        query=tool_context.query,
        sources=tool_context.sources,
        pretrip_workspace_root=tool_context.pretrip_workspace_root,
        default_limit=tool_context.default_limit,
    )
    context.invocations = invocations
    return context.tool_source_refs()


def _first_workspace_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == WORKSPACE_EVIDENCE_TOOL_ID:
            return source
    return None


def _first_risk_score_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == RISK_SCORE_TOOL_ID:
            return source
    return None


def _first_terrain_score_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == TERRAIN_SCORE_TOOL_ID:
            return source
    return None


def _first_map_perception_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == MAP_PERCEPTION_TOOL_ID:
            return source
    return None


def _first_tool_source_by_id(
    sources: list[AssistantSourceRef],
    tool_id: str,
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == tool_id:
            return source
    return None


def _without_workspace_tool_sources(
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    return [
        source
        for source in sources
        if source.source_id
        not in {
            WORKSPACE_EVIDENCE_TOOL_ID,
            RISK_SCORE_TOOL_ID,
            TERRAIN_SCORE_TOOL_ID,
            MAP_PERCEPTION_TOOL_ID,
            WORKSPACE_CATALOG_TOOL_ID,
            ROUTE_STRUCTURE_TOOL_ID,
            MAJOR_POINT_TOOL_ID,
            EVIDENCE_FULLTEXT_TOOL_ID,
        }
    ]


def _bounded_tool_limit(
    value: int | None,
    *,
    default_limit: int,
) -> int:
    if not isinstance(value, int):
        return default_limit
    return max(1, min(value, 8))


def _compact_tool_kb_result(item: dict[str, object]) -> dict[str, object]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "score": item.get("score"),
        "retrieval_rank": item.get("retrieval_rank"),
        "record_id": item.get("record_id"),
        "evidence_type": item.get("evidence_type"),
        "source_path": item.get("source_path"),
        "title": item.get("title"),
        "snippet": item.get("snippet"),
        "tags": item.get("tags", [])[:6] if isinstance(item.get("tags"), list) else [],
        "metadata": {
            key: metadata.get(key)
            for key in (
                "candidate_id",
                "note_category",
                "severity",
                "category",
                "lat",
                "lon",
                "ele_m",
                "cp_ref",
                "segment_ref",
                "mcp_id",
                "named_point_id",
                "nearest_cp_candidate_id",
                "nearest_cp_distance_m",
                "support_status",
                "review_required",
                "confidence",
                "review_state",
                "candidate_only",
            )
            if metadata.get(key) is not None
        },
        "runtime_safety_truth": False,
    }


def _looks_like_workspace_catalog_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "workspace",
            "artifact",
            "artifacts",
            "manifest",
            "tool registry",
            "資料型態",
            "資料類型",
            "有哪些資料",
            "有哪些圖層",
            "有哪些工具",
            "缺什麼",
            "工作區",
            "規格",
            "工具",
        )
    )


def _looks_like_route_structure_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "checkpoint",
            "checkpoints",
            "segment",
            "segments",
            "route structure",
            "cp",
            "有多少個cp",
            "有多少 cp",
            "幾個cp",
            "幾個 cp",
            "路線結構",
            "檢查點",
            "區段",
        )
    )


def _looks_like_major_point_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "mcp",
            "major critical",
            "named point",
            "黑水塘",
            "雲海保線所",
            "重要點",
            "關鍵點",
            "地名",
            "營地",
            "水源",
        )
    )


def _looks_like_evidence_fulltext_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "route note",
            "route notes",
            "report",
            "reports",
            "fulltext",
            "full-text",
            "search workspace",
            "危險地形",
            "崩塌",
            "營地",
            "會經過哪些",
            "有人提到",
            "路線紀錄",
            "全文",
            "搜尋",
        )
    )


def _looks_like_risk_score_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "risk score",
            "risk-score",
            "risk_score",
            "risk ribbon",
            "risk-ribbon",
            "risk heatmap",
            "risk-heatmap",
            "calibration",
            "calibrated",
            "baseline",
            "風險分數",
            "風險圖層",
            "風險校準",
            "校準",
            "校正",
            "基線",
            "熱區",
        )
    )


def _looks_like_terrain_score_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "terrain",
            "slope",
            "teii",
            "tri",
            "sri",
            "lec",
            "坡度",
            "坡",
            "陡坡",
            "地形",
            "地形分數",
            "地形圖層",
            "地形容錯",
            "低容錯",
            "最陡",
        )
    )


def _looks_like_map_perception_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "ocr",
            "annotation",
            "label",
            "tile",
            "imagery",
            "image-map",
            "contour",
            "forest",
            "grassland",
            "map perception",
            "map material",
            "圖上",
            "圖磚",
            "圖層",
            "影像",
            "標註",
            "註記",
            "文字",
            "等高線",
            "森林",
            "林班",
            "草原",
            "草坡",
            "判讀",
            "辨識",
        )
    )


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _connect_runner(runner: PydanticAIRunner, *, timeout_seconds: int) -> None:
    connector = getattr(runner, "connect", None)
    if callable(connector):
        connector(timeout_seconds=timeout_seconds)
        return
    runner.run(
        "Scout assistant connectivity check. Reply with OK.",
        timeout_seconds=timeout_seconds,
    )
