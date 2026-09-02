from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRH_SPEC = ROOT / "docs/specs/scout-terrain-route-hypothesis.md"
OUTDOOR_STANDARD = ROOT / "docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md"


def test_trh_spec_documents_reviewed_r4_without_authority_promotion() -> None:
    text = TRH_SPEC.read_text(encoding="utf-8")

    assert "R4 historical_narrative_guided" in text
    assert "Scout Pydantic AI typed constraint plan" in text
    assert "explicit map-point review" in text
    assert "raw narrative" in text.lower()
    assert "candidate_only" in text
    assert "runtime_safety_truth=false" in text
    assert "does not\nchange the source to `human_verified`" in text
    assert "Any failed segment makes the guided calculation\nunavailable" in text
    assert "Changing A/B invalidates every prior guidance review" in text
    assert "ridge-local-minimum saddle proxies" in text
    assert "no\n   automatic anchor selection is made" in text
    assert "Sequence ranking" in text
    assert "hash-bound candidate corridor overlap" in text
    assert "candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation" in text
    assert "does not filter candidates or select an anchor" in text


def test_navigation_force_standard_preserves_guided_trh_fail_closed_contract() -> None:
    text = OUTDOOR_STANDARD.read_text(encoding="utf-8")

    assert "### 11.12 Scout AI 歷史敘事引導與 R4" in text
    assert "`MAP-WAYFIND-011`" in text
    assert "`MAP-WAYFIND-012`" in text
    assert "human map-point annotation + review artifact" in text
    assert "ordered r.walk + r.path segments" in text
    assert "不是 `human_verified trail`" in text
    assert "runtime_safety_truth=false" in text
    assert "前進／撤退 authority" in text
    assert "guided_execution_ready=false" in text
    assert "ridge 上的局部低點" in text
    assert "排序不得視為自動選點" in text
    assert "Sampling failure、NoData 或不完整回傳" in text
    assert "`MAP-WAYFIND-013`" in text
    assert "candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation" in text
    assert "候選不得因 overlap 為 0 而被移除" in text
