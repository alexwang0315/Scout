from scout_diagnostic_taxonomy import (
    CORRECTNESS_GATE_FAMILIES,
    SCOUT_AI_SCORE_FAMILIES,
    DiagnosticPurpose,
    family_for,
)
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_has_two_non_overlapping_purposes():
    assert SCOUT_AI_SCORE_FAMILIES
    assert CORRECTNESS_GATE_FAMILIES
    assert {family.family_id for family in SCOUT_AI_SCORE_FAMILIES}.isdisjoint(
        family.family_id for family in CORRECTNESS_GATE_FAMILIES
    )
    assert all(family.purpose is DiagnosticPurpose.SCOUT_AI_SCORE for family in SCOUT_AI_SCORE_FAMILIES)
    assert all(family.purpose is DiagnosticPurpose.CORRECTNESS_GATE for family in CORRECTNESS_GATE_FAMILIES)


def test_known_families_explain_different_failure_actions():
    assert "分數" in family_for("answer_quality").failure_action
    assert "FAIL" in family_for("runtime_and_safety").failure_action
    assert family_for("workspace_and_identity").purpose is DiagnosticPurpose.CORRECTNESS_GATE


def test_dashboard_exposes_independent_ai_score_and_correctness_sections():
    source = (ROOT / "docs/admin/scout-dashboard-v0.1.html").read_text(encoding="utf-8")
    assert 'data-diagnostic-purpose="scout-ai-score"' in source
    assert 'data-diagnostic-purpose="correctness-gate"' in source
    assert "aiScoreCases" in source
    assert "不納入下方 Correctness Gate 統計" in source
