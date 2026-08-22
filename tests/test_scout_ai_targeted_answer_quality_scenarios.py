from __future__ import annotations

from collections import Counter
from pathlib import Path

from scout_ai_six_forces_scenarios import (
    ScenarioContext,
    load_question_templates,
)
from scout_ai_targeted_answer_quality_scenarios import (
    EXPECTED_FAMILY_COUNTS,
    EXPECTED_FORCE_COUNTS,
    generate_targeted_case_mapping,
    load_targeted_questions,
    targeted_artifact_statistics,
)
from tools.scout_ai_six_forces_aihat2_eval import (
    apply_local_recovery_grounding_guard,
    build_recovery_prompt,
    expand_case_runs,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/specs/scout-ai-targeted-answer-quality-100-question-corpus.md"
SIX_FORCES_CORPUS = ROOT / "docs/specs/scout-ai-six-forces-600-question-corpus.md"


def _scenarios() -> list[ScenarioContext]:
    return [
        ScenarioContext(
            scenario_id=f"targeted.boss-approach.rank-{rank}.v1",
            source_mode="synthetic_replay",
            project_id="targeted-test",
            observed_at="2026-08-16T08:00:00+08:00",
            boss_point_id=f"boss.{rank:03d}",
            boss_rank=rank,
            lat=24.05 + rank / 1000,
            lon=121.21 + rank / 1000,
            horizontal_accuracy_m=5,
            fix_quality="synthetic_route_interpolation",
            route_progress_m=rank * 1000,
            distance_to_boss_along_route_m=500,
            nearest_route_distance_m=0,
            heading_deg=90,
            travel_direction="increasing_route_progress",
            risk_terrain_candidate={},
            source_refs=[],
            condition_overlay_refs=[],
        )
        for rank in range(1, 6)
    ]


def test_targeted_corpus_has_expected_unique_distribution() -> None:
    questions, corpus_hash = load_targeted_questions(CORPUS)

    assert len(questions) == 100
    assert len(corpus_hash) == 64
    assert Counter(item.force_code for item in questions) == Counter(
        EXPECTED_FORCE_COUNTS
    )
    assert Counter(item.failure_family_code for item in questions) == Counter(
        EXPECTED_FAMILY_COUNTS
    )
    assert len({item.question_text for item in questions}) == 100


def test_targeted_questions_do_not_repeat_six_forces_corpus_text() -> None:
    targeted, _ = load_targeted_questions(CORPUS)
    existing, _ = load_question_templates(SIX_FORCES_CORPUS)

    overlap = {item.question_text for item in targeted} & {
        str(item["question_text"]) for item in existing
    }

    assert overlap == set()


def test_targeted_cases_remain_compatible_with_existing_eval_harness() -> None:
    scenarios = _scenarios()
    cases, contracts, corpus_hash = generate_targeted_case_mapping(
        CORPUS,
        scenarios,
    )
    artifact = {
        "scenarios": [item.model_dump(mode="json") for item in scenarios],
        "cases": [item.model_dump(mode="json") for item in cases],
    }

    runs = expand_case_runs(artifact)

    assert len(cases) == 100
    assert len(contracts) == 100
    assert len(corpus_hash) == 64
    assert len(runs) == 210
    assert Counter(item["force_code"] for item in runs) == Counter(
        {
            "EXP": 30,
            "RPF": 5,
            "PER": 45,
            "RTE": 5,
            "WTH": 120,
            "NAV": 5,
        }
    )
    assert all(item["candidate_only"] for item in runs)
    assert not any(item["runtime_safety_truth"] for item in runs)
    assert all(
        item.question_source_ref.startswith(
            "docs/specs/scout-ai-targeted-answer-quality-100-question-corpus.md#"
        )
        for item in cases
    )


def test_targeted_contracts_cover_every_failure_family() -> None:
    questions, _ = load_targeted_questions(CORPUS)
    cases, contracts, _ = generate_targeted_case_mapping(CORPUS, _scenarios())
    statistics = targeted_artifact_statistics(questions)

    assert {item.question_id for item in contracts} == {
        item.question_id for item in cases
    }
    assert all(item.source_failure_ids for item in contracts)
    assert all(item.expected_behaviors for item in contracts)
    assert all(item.forbidden_behaviors for item in contracts)
    assert statistics == {
        "base_question_count": 100,
        "expanded_model_run_count": 210,
        "force_counts": dict(sorted(EXPECTED_FORCE_COUNTS.items())),
        "failure_family_counts": dict(sorted(EXPECTED_FAMILY_COUNTS.items())),
    }


def _recovery_run(*, answer_mode: str, variant_id: str) -> dict[str, object]:
    return {
        "expected_decision_boundary": {"answer_mode": answer_mode},
        "question_text": "這是一個需要修正的問題嗎？",
        "scenario_id": f"targeted.{variant_id}",
        "variant_id": variant_id,
    }


def test_local_recovery_for_question_specific_gap_forbids_extra_facts() -> None:
    prompt = build_recovery_prompt(
        run=_recovery_run(answer_mode="factual_context", variant_id="base"),
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.route_context.assess.v0",
                    "field_answer": "只有候選地名，沒有題目專屬史料。",
                }
            ],
            "blocking_missing_evidence": [
                "question_specific_route_context_evidence_missing"
            ],
            "missing_evidence": [],
        },
        previous_output={"decision": None, "answer": "不受支持的推測"},
        verifier_errors=["question_specific_gap_not_answered_first"],
        model_profile="local",
    )

    assert "唯一決策:null" in prompt
    assert "A 只能逐字輸出『必要原文』" in prompt
    assert "必要原文:工作區未提供足夠的題目專屬證據，無法確認。" in prompt


def test_local_recovery_requires_literal_severe_weather_signals() -> None:
    prompt = build_recovery_prompt(
        run=_recovery_run(
            answer_mode="decision",
            variant_id="severe_fresh_route_intersecting",
        ),
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.weather_window.assess.v0",
                    "decision": "CHANGE_PLAN",
                    "field_answer": "劇烈天氣已與路線交會，建議改變計畫。",
                }
            ],
            "supporting_evidence": [
                {
                    "tool_id": "scout.ai.cwa_environment.assess.v0",
                    "field_answer": "Direct QPF unavailable，PoP peak=60%。",
                }
            ],
            "blocking_missing_evidence": [],
            "missing_evidence": [],
        },
        previous_output={"decision": "CHANGE_PLAN", "answer": "避開壞天氣。"},
        verifier_errors=["severe_weather_not_used"],
        model_profile="local",
    )

    assert "唯一決策:CHANGE_PLAN" in prompt
    assert "題目專屬證據:scout.ai.cwa_environment.assess.v0" in prompt
    assert "signals=heavy_rain, strong_wind, low_visibility" in prompt
    assert "先避開暴露或高風險時段後重評" in prompt


def test_local_recovery_pins_decision_to_primary_scenario_tool() -> None:
    prompt = build_recovery_prompt(
        run=_recovery_run(
            answer_mode="decision",
            variant_id="benign_fresh_route_intersecting",
        ),
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.weather_window.assess.v0",
                    "decision": "GO",
                    "field_answer": "天氣證據與路線無交會，只就天氣面可行。",
                }
            ],
            "blocking_missing_evidence": [],
            "missing_evidence": [],
        },
        previous_output={"decision": "NO_GO", "answer": "地形風險過高。"},
        verifier_errors=["decision_outside_scenario_boundary"],
        model_profile="local",
    )

    assert "唯一決策:GO" in prompt
    assert "必要原文:天氣證據與路線無交會，只就天氣面可行。" in prompt


def test_local_grounding_guard_clamps_unsupported_gap_answer() -> None:
    output, actions = apply_local_recovery_grounding_guard(
        output={
            "answer": "黑水塘是污染物蓄積地。",
            "decision": "GO",
            "evidence_gaps": [],
        },
        compact_evidence={"tools": []},
        repair_errors=["question_specific_gap_not_answered_first"],
        answer_mode="factual_context",
    )

    assert output is not None
    assert output["answer"] == "工作區未提供足夠的題目專屬證據，無法確認。"
    assert output["decision"] is None
    assert output["evidence_gaps"] == [
        "question_specific_route_context_evidence_missing"
    ]
    assert actions == ["question_specific_gap_clamped"]


def test_local_grounding_guard_restores_weather_and_question_evidence() -> None:
    output, actions = apply_local_recovery_grounding_guard(
        output={
            "answer": "避開壞天氣。",
            "decision": "DELAY",
            "evidence_gaps": [],
        },
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.weather_window.assess.v0",
                    "decision": "CHANGE_PLAN",
                    "field_answer": (
                        "signals=heavy_rain, strong_wind, low_visibility 已與 route "
                        "corridor 相交；先避開暴露時段後重評。"
                    ),
                }
            ],
            "supporting_evidence": [
                {
                    "tool_id": "scout.ai.cwa_environment.assess.v0",
                    "field_answer": "Direct QPF unavailable，PoP peak=60%。",
                }
            ],
        },
        repair_errors=["severe_weather_not_used"],
        answer_mode="decision",
    )

    assert output is not None
    assert output["decision"] == "CHANGE_PLAN"
    assert output["answer"].startswith("Direct QPF unavailable")
    assert "signals=heavy_rain, strong_wind, low_visibility" in output["answer"]
    assert actions == ["severe_weather_evidence_restored"]


def test_local_grounding_guard_restores_benign_weather_boundary() -> None:
    field_answer = (
        "signals=no_significant_rain, light_wind, good_visibility；"
        "只就天氣面可行；仍需核對地形、隊伍與裝備。"
    )
    output, actions = apply_local_recovery_grounding_guard(
        output={
            "answer": "降雨機率是預估雨量。",
            "decision": "NO_GO",
            "evidence_gaps": [],
        },
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.weather_window.assess.v0",
                    "decision": "CONDITIONAL_GO",
                    "field_answer": field_answer,
                }
            ]
        },
        repair_errors=["benign_weather_cross_domain_checks_missing"],
        answer_mode="decision",
    )

    assert output is not None
    assert output["decision"] == "CONDITIONAL_GO"
    assert output["answer"] == field_answer
    assert actions == ["benign_weather_boundary_restored"]


def test_local_grounding_guard_restores_primary_scenario_decision() -> None:
    output, actions = apply_local_recovery_grounding_guard(
        output={
            "answer": "無關的地形 NO_GO。",
            "decision": "NO_GO",
            "evidence_gaps": [],
        },
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.ai.weather_window.assess.v0",
                    "decision": "GO",
                    "field_answer": "polygon 未與 route corridor 相交，只就天氣面可行。",
                }
            ]
        },
        repair_errors=["decision_outside_scenario_boundary"],
        answer_mode="decision",
    )

    assert output is not None
    assert output["decision"] == "GO"
    assert output["answer"] == "polygon 未與 route corridor 相交，只就天氣面可行。"
    assert actions == ["primary_scenario_decision_restored"]
