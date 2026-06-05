from __future__ import annotations

from pathlib import Path

from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery
from assistant_skill_router import (
    PRETRIP_CP_COUNT_SKILL_ID,
    PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
    PRETRIP_PLACE_TO_CP_SKILL_ID,
    augment_pretrip_sources_with_local_evidence_search,
    build_pretrip_local_evidence_search_source,
    resolve_assistant_query_with_skill,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_pretrip_local_evidence_search_source_finds_workspace_evidence() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="大崩塌有什麼風險？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    source = build_pretrip_local_evidence_search_source(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
    )

    assert source is not None
    assert source.source_id == PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID
    assert source.evidence_type == "assistant_local_evidence_search_results"
    summary = source.context_summary
    assert summary is not None
    assert summary["result_count"] >= 1
    assert summary["searched_record_count"] > 100
    assert summary["runtime_safety_truth"] is False
    assert summary["raw_payloads_embedded"] is False
    assert any("大崩塌" in result["snippet"] for result in summary["results"])


def test_pretrip_local_evidence_search_source_includes_mcp_metadata() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="黑水塘有什麼資料？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    source = build_pretrip_local_evidence_search_source(
        query,
        project_root=PROJECT_ROOT,
        limit=5,
    )

    assert source is not None
    summary = source.context_summary
    assert summary is not None
    results = summary["results"]
    assert any(
        result["evidence_type"] == "pretrip_major_critical_point_candidate"
        and result["metadata"]["mcp_id"] == "mcp.heishuitang.002"
        and result["metadata"]["nearest_cp_candidate_id"] == "cp.002"
        for result in results
    )
    assert any(
        result["evidence_type"] == "pretrip_mcp_cp_support_reconciliation"
        and result["metadata"]["support_status"] == "supported"
        for result in results
    )
    assert any(
        result["evidence_type"] == "pretrip_mcp_named_point"
        and result["metadata"]["named_point_id"] == "np.heishuitang"
        for result in results
    )


def test_pretrip_local_evidence_search_source_is_added_only_for_general_questions() -> None:
    general_query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="大崩塌有什麼風險？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    deterministic_query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="有多少個cp",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = [_pretrip_context_source()]

    general_sources = augment_pretrip_sources_with_local_evidence_search(
        general_query,
        sources=sources,
        project_root=PROJECT_ROOT,
    )
    deterministic_sources = augment_pretrip_sources_with_local_evidence_search(
        deterministic_query,
        sources=sources,
        project_root=PROJECT_ROOT,
    )

    assert general_sources[0].source_id == PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID
    assert deterministic_sources == sources


def test_pretrip_cp_count_skill_resolves_from_context_summary() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="有多少個cp",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    response = resolve_assistant_query_with_skill(
        query,
        sources=[_pretrip_context_source()],
    )

    assert response is not None
    assert response.answer.startswith("Scout AI read-only deterministic skill result")
    assert "124 個 CP" in response.answer
    assert "runtime safety truth" in response.answer
    assert response.sources[0].source_id == PRETRIP_CP_COUNT_SKILL_ID
    assert any(
        limitation == f"resolved_by={PRETRIP_CP_COUNT_SKILL_ID}"
        for limitation in response.limitations
    )


def test_pretrip_place_to_cp_skill_resolves_from_context_summary() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="黑水塘在第幾cp附近？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = [_pretrip_context_source()]

    response = resolve_assistant_query_with_skill(query, sources=sources)

    assert response is not None
    assert response.answer.startswith("Scout AI read-only deterministic skill result")
    assert "黑水塘 在 CP 006 附近" in response.answer
    assert "58.519 m" in response.answer
    assert "candidate_only=true" in response.answer
    assert "runtime_safety_truth=false" in response.answer
    assert response.sources[0].source_id == PRETRIP_PLACE_TO_CP_SKILL_ID
    assert response.boundary.pretrip_review_mutation_allowed is False
    assert response.boundary.safety_mutation_allowed is False
    assert any(
        limitation == f"resolved_by={PRETRIP_PLACE_TO_CP_SKILL_ID}"
        for limitation in response.limitations
    )


def test_pretrip_place_to_cp_skill_defers_when_no_place_match() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="不存在地點在第幾cp附近？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    assert (
        resolve_assistant_query_with_skill(query, sources=[_pretrip_context_source()])
        is None
    )


def _pretrip_context_source() -> AssistantSourceRef:
    return AssistantSourceRef(
        source_id="assistant_context.pretrip",
        source_path="pretrip_assistant_context",
        evidence_type="assistant_context_summary",
        selected=True,
        context_summary={
            "surface": "pretrip",
            "summary": {
                "cp_count": 124,
                "checkpoint_candidate_count": 124,
                "major_critical_point_cp_links": [
                    {
                        "label": "黑水塘",
                        "mcp_id": "mcp.heishuitang.002",
                        "nearest_cp_candidate_id": "cp.006",
                        "nearest_cp_label": "CP 006",
                        "nearest_cp_distance_m": 58.519,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "support_status": "supported",
                    }
                ]
            },
        },
    )
