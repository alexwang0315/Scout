from __future__ import annotations

from pathlib import Path
from typing import Any

from assistant_models import (
    AssistantBoundary,
    AssistantSourceRef,
    AssistantSurface,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)


PRETRIP_PLACE_TO_CP_SKILL_ID = "assistant_skill.pretrip.place_to_cp.v0"
PRETRIP_CP_COUNT_SKILL_ID = "assistant_skill.pretrip.cp_count.v0"
PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID = (
    "assistant_skill.pretrip.local_evidence_search.v0"
)


def augment_pretrip_sources_with_local_evidence_search(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    project_root: Path | None,
    limit: int = 5,
) -> list[AssistantSourceRef]:
    if query.surface != AssistantSurface.PRETRIP or project_root is None:
        return sources
    if resolve_assistant_query_with_skill(query, sources=sources) is not None:
        return sources

    search_source = build_pretrip_local_evidence_search_source(
        query,
        project_root=project_root,
        limit=limit,
    )
    if search_source is None:
        return sources
    return [search_source, *sources]


def build_pretrip_local_evidence_search_source(
    query: ScoutAssistantQuery,
    *,
    project_root: Path,
    limit: int = 5,
) -> AssistantSourceRef | None:
    search_text = query.question.strip()
    if not search_text:
        return None

    try:
        from scout_agent_kb import query_project_local_evidence

        result = query_project_local_evidence(
            project_root,
            query=search_text,
            limit=limit,
        )
        context_summary = {
            "resolver": PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
            "query": result.query,
            "project_id": result.project_id,
            "retrieval_engine": result.retrieval_engine,
            "result_count": result.result_count,
            "searched_record_count": result.searched_record_count,
            "results": [_compact_kb_result(item) for item in result.results],
            "boundary": result.boundary.model_dump(mode="json"),
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        }
    except Exception as exc:  # Defensive: search failures must not break assistant.
        context_summary = {
            "resolver": PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
            "query": search_text,
            "project_root_available": project_root.is_dir(),
            "status": "failed",
            "error_type": type(exc).__name__,
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        }

    return AssistantSourceRef(
        source_id=PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
        source_path="scout_agent_kb.query_project_local_evidence",
        evidence_type="assistant_local_evidence_search_results",
        selected=True,
        context_summary=context_summary,
    )


def build_local_evidence_search_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    search_source = _local_evidence_search_source(sources)
    if search_source is None:
        return None
    summary = search_source.context_summary or {}
    results = summary.get("results")
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
        "Scout AI local evidence fallback: Pydantic AI provider was unavailable, "
        "so this read-only answer shows local workspace evidence search results. "
        f"Question: {query.question}. "
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
            f"resolved_by={PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID}",
            "Local evidence fallback summarized bounded search snippets after provider failure.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _local_evidence_search_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID:
            return source
    return None


def _compact_kb_result(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "score": item.get("score"),
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


def resolve_assistant_query_with_skill(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    if query.surface == AssistantSurface.PRETRIP:
        cp_count_response = _resolve_pretrip_cp_count(query, sources=sources)
        if cp_count_response is not None:
            return cp_count_response
        return _resolve_pretrip_place_to_cp(query, sources=sources)
    return None


def _resolve_pretrip_cp_count(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    if not _looks_like_cp_count_question(query.question):
        return None

    summary = _pretrip_context_summary(sources)
    cp_count = summary.get("cp_count") or summary.get("checkpoint_candidate_count")
    if not isinstance(cp_count, int):
        return None

    source_id = "assistant_context.pretrip"
    answer = (
        f"目前 pretrip context 有 {cp_count} 個 CP "
        "(checkpoint candidates)。這個數字使用 cp_count / "
        "checkpoint_candidate_count；它是行前候選/規劃 evidence，"
        "不是 runtime safety truth。Source: assistant_context.pretrip."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=f"Scout AI read-only deterministic skill result: {answer}",
        sources=_skill_sources(
            sources,
            skill_id=PRETRIP_CP_COUNT_SKILL_ID,
            source_id=source_id,
        ),
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"resolved_by={PRETRIP_CP_COUNT_SKILL_ID}",
            "Deterministic resolver used structured pretrip context before invoking a model.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _resolve_pretrip_place_to_cp(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    if not _looks_like_place_to_cp_question(query.question):
        return None

    links = _pretrip_place_cp_links(sources)
    link = _match_place_link(query.question, links)
    if link is None:
        return None

    nearest_cp = link.get("nearest_cp_label") or link.get("nearest_cp_candidate_id")
    if not nearest_cp:
        return None

    label = str(link.get("label") or "requested place")
    distance = _format_distance_m(link.get("nearest_cp_distance_m"))
    source_id = str(link.get("mcp_id") or "assistant_context.pretrip")
    candidate_only = bool(link.get("candidate_only"))
    runtime_truth = bool(link.get("runtime_safety_truth"))
    support_status = link.get("support_status")

    answer = (
        f"{label} 在 {nearest_cp} 附近"
        f"{f'，與最近 CP 距離約 {distance}' if distance else ''}。"
        "這是 pretrip MCP-to-CP candidate evidence；"
        f"candidate_only={str(candidate_only).lower()}，"
        f"runtime_safety_truth={str(runtime_truth).lower()}。"
        f"Source: {source_id}, assistant_context.pretrip."
    )
    if support_status:
        answer += f" support_status={support_status}."

    return ScoutAssistantResponse(
        surface=query.surface,
        answer=f"Scout AI read-only deterministic skill result: {answer}",
        sources=_skill_sources(sources, source_id=source_id),
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"resolved_by={PRETRIP_PLACE_TO_CP_SKILL_ID}",
            "Deterministic resolver used structured pretrip context before invoking a model.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _looks_like_place_to_cp_question(question: str) -> bool:
    normalized = question.lower().replace(" ", "")
    cp_terms = ("cp", "checkpoint", "檢查點")
    place_terms = ("附近", "靠近", "第幾", "哪個", "接近")
    return any(term in normalized for term in cp_terms) and any(
        term in normalized for term in place_terms
    )


def _looks_like_cp_count_question(question: str) -> bool:
    normalized = question.lower().replace(" ", "")
    cp_terms = ("cp", "checkpoint", "檢查點")
    count_terms = ("多少", "幾個", "幾個", "總數", "count", "number")
    place_to_cp_terms = ("第幾", "附近", "靠近", "哪個", "接近")
    return (
        any(term in normalized for term in cp_terms)
        and any(term in normalized for term in count_terms)
        and not any(term in normalized for term in place_to_cp_terms)
    )


def _pretrip_place_cp_links(sources: list[AssistantSourceRef]) -> list[dict[str, Any]]:
    summary = _pretrip_context_summary(sources)
    links = summary.get("major_critical_point_cp_links")
    if isinstance(links, list):
        return [link for link in links if isinstance(link, dict)]
    return []


def _pretrip_context_summary(sources: list[AssistantSourceRef]) -> dict[str, Any]:
    for source in sources:
        if source.source_id != "assistant_context.pretrip":
            continue
        context = source.context_summary or {}
        summary = context.get("summary")
        if not isinstance(summary, dict):
            continue
        return summary
    return {}


def _match_place_link(
    question: str,
    links: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for link in links:
        for name in _place_names(link):
            if name and name in question:
                candidates.append((len(name), link))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _place_names(link: dict[str, Any]) -> list[str]:
    names: list[str] = []
    label = link.get("label")
    if isinstance(label, str):
        names.append(label)
    aliases = link.get("aliases")
    if isinstance(aliases, list):
        names.extend(alias for alias in aliases if isinstance(alias, str))
    return names


def _format_distance_m(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    if abs(float(value) - round(float(value))) < 0.001:
        return f"{float(value):.1f} m"
    return f"{float(value):.3f} m"


def _skill_sources(
    sources: list[AssistantSourceRef],
    *,
    skill_id: str = PRETRIP_PLACE_TO_CP_SKILL_ID,
    source_id: str,
) -> list[AssistantSourceRef]:
    skill_source = AssistantSourceRef(
        source_id=skill_id,
        source_path="assistant_skill_router",
        evidence_type="assistant_deterministic_skill",
        selected=True,
        context_summary={
            "resolver": skill_id,
            "source_id": source_id,
            "read_only": True,
            "runtime_safety_truth": False,
        },
    )
    return [skill_source, *sources]
