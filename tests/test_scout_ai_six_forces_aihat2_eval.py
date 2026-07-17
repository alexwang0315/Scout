from __future__ import annotations

import json
from pathlib import Path

from tools.scout_ai_six_forces_aihat2_eval import (
    _write_summaries,
    build_recovery_prompt,
    build_structured_prompt,
    compact_evidence_for_model,
    expand_case_runs,
    health_guard,
    parse_model_output,
    snapshot_for_run,
    verify_model_output,
)
from tools.scout_ai_aihat2_fallback_eval import _compact_tool_result


def _artifact() -> dict:
    scenarios = [
        {
            "scenario_id": "route.rank-1.v1",
            "source_mode": "synthetic_replay",
            "project_id": "demo",
            "observed_at": "2026-07-16T08:00:00+08:00",
            "boss_point_id": "boss.001",
            "boss_rank": 1,
            "lat": 24.05,
            "lon": 121.22,
            "horizontal_accuracy_m": 5,
            "fix_quality": "synthetic_route_interpolation",
            "route_progress_m": 1000,
            "distance_to_boss_along_route_m": 500,
            "nearest_route_distance_m": 0,
            "heading_deg": 90,
            "travel_direction": "increasing_route_progress",
            "risk_terrain_candidate": {},
            "source_refs": [],
            "condition_overlay_refs": [],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    cases = []
    for force in ("EXP", "RPF", "PER", "RTE", "WTH", "NAV"):
        cases.append(
            {
                "case_id": f"six600.{force}-001.route.rank-1.v1",
                "question_id": f"{force}-001",
                "global_ordinal": len(cases) + 1,
                "force_code": force,
                "force_name": force,
                "capability_name": force,
                "force_ordinal": 1,
                "subsection": "test",
                "question_text": "這裡現在應該怎麼判斷？",
                "question_source_ref": "corpus.md#sha256=x",
                "question_record_sha256": "x",
                "scenario_id": "route.rank-1.v1",
                "expected_evidence_contract": {
                    "required_context": ["scenario_location"],
                    "required_evidence": ["weather"],
                    "scenario_identity_match_required": True,
                    "provenance_required": True,
                    "freshness_required": force in {"PER", "WTH"},
                    "route_intersection_required": force in {"PER", "WTH"},
                    "missing_semantics": "unknown_not_permission",
                    "candidate_status_policy": "candidate_must_remain_unconfirmed",
                    "required_answer_elements": [
                        "decisive_evidence",
                        "opposing_evidence",
                        "evidence_gaps",
                        "decision_change_conditions",
                        "source_refs",
                    ],
                },
                "expected_decision_boundary": {
                    "answer_mode": "decision" if force in {"PER", "WTH"} else "compound",
                    "allowed_decisions": ["GO", "CHANGE_PLAN", "DELAY"],
                    "forbidden_claims": ["guaranteed safe"],
                },
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return {"project_id": "demo", "scenarios": scenarios, "cases": cases}


def test_expands_every_permission_and_weather_case_to_three_contexts() -> None:
    runs = expand_case_runs(_artifact())

    assert len(runs) == 10
    assert len([item for item in runs if item["force_code"] == "PER"]) == 3
    assert len([item for item in runs if item["force_code"] == "WTH"]) == 3
    assert len({item["run_case_id"] for item in runs}) == 10


def test_per095_uses_exact_three_context_decision_boundaries() -> None:
    artifact = _artifact()
    permission_case = next(
        item for item in artifact["cases"] if item["force_code"] == "PER"
    )
    permission_case["question_id"] = "PER-095"
    permission_case["case_id"] = "six600.PER-095.route.rank-1.v1"

    runs = [item for item in expand_case_runs(artifact) if item["force_code"] == "PER"]

    assert {item["variant_id"]: item["expected_decisions"] for item in runs} == {
        "exposed_strong_wind_shelter_ahead": ["CHANGE_PLAN"],
        "sheltered_flat_time_available": ["CONDITIONAL_GO"],
        "gnss_stale_location_unknown": ["DELAY"],
    }


def test_stale_permission_context_does_not_claim_location() -> None:
    run = next(
        item
        for item in expand_case_runs(_artifact())
        if item["force_code"] == "PER"
        and item["variant_id"] == "gnss_stale_location_unknown"
    )

    snapshot = snapshot_for_run(run)

    assert snapshot["scenario_id"] == run["scenario_id"]
    assert snapshot["fix_quality"] == "stale_unknown"
    assert "lat" not in snapshot
    assert "route_progress_m" not in snapshot


def test_structured_prompt_excludes_reference_and_allowed_decisions() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "PER")
    prompt = build_structured_prompt(
        run=run,
        compact_evidence={"scenario_id": run["scenario_id"], "source_refs": ["a.json"]},
    )

    assert "deterministic_reference" not in prompt
    assert "allowed_decisions" not in prompt
    assert run["question_text"] in prompt
    assert "candidate_only" in prompt


def test_structured_prompt_uses_missing_evidence_response_mode_without_reference() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")

    prompt = build_structured_prompt(
        run=run,
        compact_evidence={
            "scenario_id": run["scenario_id"],
            "missing_evidence": ["question_specific_route_context_evidence_missing"],
            "tools": [],
        },
    )

    assert "工作區未提供足夠的題目專屬證據，無法確認" in prompt
    assert "deterministic_reference" not in prompt


def test_parser_extracts_json_and_verifier_checks_scenario() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "PER")
    raw = "result:\n" + json.dumps(
        {
            "scenario_id": run["scenario_id"],
            "decision": "CHANGE_PLAN",
            "answer": "先移動到前方背風候選點再評估。",
            "decisive_evidence": ["強風且目前為暴露候選地形"],
            "opposing_evidence": ["仍有時間緩衝"],
            "evidence_gaps": [],
            "decision_change_conditions": ["風勢下降且確認背風平坦"],
            "source_refs": ["a.json"],
            "claims": ["candidate evidence only"],
        },
        ensure_ascii=False,
    )
    parsed, error = parse_model_output(raw)
    verified = verify_model_output(
        run=run,
        output=parsed,
        parse_error=error,
        available_source_refs={"a.json"},
    )

    assert error is None
    assert verified["status"] == "pass"


def test_permission_verifier_rejects_claim_that_shelter_path_does_not_exist() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "PER")
    output = {
        "scenario_id": run["scenario_id"],
        "decision": "NO_GO",
        "answer": "不能停留，因為前方沒有安全路徑。",
        "decisive_evidence": ["強風"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": [],
        "source_refs": ["tool"],
        "claims": ["candidate_only"],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"tool"},
    )

    assert "contradicts_sheltered_candidate_ahead" in verified["errors"]


def test_parser_expands_compact_local_model_schema() -> None:
    parsed, error = parse_model_output(
        '{"s":"scenario.1","d":"DELAY","a":"先等候","e":"定位過期",'
        '"o":"","g":"GNSS stale","c":"定位恢復","r":"tool.id","cl":"candidate_only"}'
    )

    assert error is None
    assert parsed == {
        "scenario_id": "scenario.1",
        "decision": "DELAY",
        "answer": "先等候",
        "decisive_evidence": ["定位過期"],
        "opposing_evidence": [],
        "evidence_gaps": ["GNSS stale"],
        "decision_change_conditions": ["定位恢復"],
        "source_refs": ["tool.id"],
        "claims": ["candidate_only"],
    }


def test_parser_normalizes_hailo_fullwidth_quotes_and_source_prefix() -> None:
    parsed, error = parse_model_output(
        "{＂s＂:＂scenario.1＂,＂d＂:null,＂a＂:＂短答＂,＂e＂:＂證據＂,"
        "＂o＂:＂＂,＂g＂:＂＂,＂c＂:＂條件＂,＂r＂:＂tool_id：scout.ai.route_context.assess.v0＂,"
        "＂cl＂:＂candidate_only＂}"
    )

    assert error is None
    assert parsed["source_refs"] == ["scout.ai.route_context.assess.v0"]


def test_full_artifact_expands_to_one_thousand_when_available() -> None:
    path = Path(
        "/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/"
        "scout_ai_six_forces_600_scenarios.json"
    )
    if not path.exists():
        return

    runs = expand_case_runs(json.loads(path.read_text(encoding="utf-8")))

    assert len(runs) == 1000
    assert len({item["question_id"] for item in runs}) == 600
    assert len({item["run_case_id"] for item in runs}) == 1000


def test_health_guard_warns_on_historical_flags_but_fails_current_flags() -> None:
    historical = health_guard(
        {
            "temp": {"stdout": "temp=56.5'C"},
            "throttled": {"stdout": "throttled=0x50000"},
            "ups": {"power_supplies": []},
        }
    )
    current = health_guard(
        {
            "temp": {"stdout": "temp=56.5'C"},
            "throttled": {"stdout": "throttled=0x50005"},
            "ups": {"power_supplies": []},
        }
    )

    assert historical["status"] == "warn"
    assert current["status"] == "fail"


def test_tool_adapter_preserves_top_level_field_answer_with_result_records() -> None:
    compact = _compact_tool_result(
        {
            "tool_id": "scout.ai.route_context.assess.v0",
            "status": "completed",
            "payload": {
                "answerability": "route_context_available",
                "field_answer": "15K 位於候選 CP-015 附近。",
                "field_answer_priority": 100,
                "field_answer_source_ref": "candidates/route_mileage_k_anchors.json",
                "results": [{"label": "15K", "source_path": "anchors.json"}],
            },
        }
    )

    assert compact["field_answer"] == "15K 位於候選 CP-015 附近。"
    assert compact["field_answer_priority"] == 100
    assert compact["field_answer_source_ref"] == "candidates/route_mileage_k_anchors.json"


def test_compact_evidence_marks_low_priority_route_context_as_gap() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    evidence = compact_evidence_for_model(
        run=run,
        total_info=None,
        tool_results=[
            {
                "tool_id": "scout.ai.route_context.assess.v0",
                "status": "completed",
                "answerability": "route_context_available",
                "field_answer": "只有泛用候選點。",
                "field_answer_priority": 0,
                "field_answer_source_ref": "candidates/route_context_points.json",
                "records": [{"label": "203", "context_kind": "route_context"}],
            }
        ],
        missing_tools=[],
        missing_evidence=[],
    )

    assert "question_specific_route_context_evidence_missing" in evidence["missing_evidence"]
    assert evidence["tools"][0]["field_answer"] == "只有泛用候選點。"


def test_verifier_rejects_unsupported_factual_claim_when_specific_evidence_is_missing() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    output = {
        "scenario_id": run["scenario_id"],
        "decision": None,
        "answer": "這座山主要由花崗岩構成。",
        "decisive_evidence": ["花崗岩"],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": ["取得地質圖"],
        "source_refs": ["scout.ai.route_context.assess.v0"],
        "claims": ["candidate_only"],
    }
    evidence = {
        "missing_evidence": ["question_specific_route_context_evidence_missing"],
        "tools": [
            {
                "tool_id": "scout.ai.route_context.assess.v0",
                "field_answer": "只有泛用候選點。",
                "record": "203 route_context",
            }
        ],
    }

    verified = verify_model_output(
        run=run,
        output=output,
        parse_error=None,
        available_source_refs={"scout.ai.route_context.assess.v0"},
        compact_evidence=evidence,
    )

    assert "unsupported_answer_despite_question_specific_evidence_gap" in verified["errors"]
    assert "missing_evidence_not_preserved" in verified["errors"]


def test_recovery_prompt_carries_verifier_feedback_without_reference_answer() -> None:
    run = next(item for item in expand_case_runs(_artifact()) if item["force_code"] == "EXP")
    evidence = {
        "scenario_id": run["scenario_id"],
        "missing_evidence": ["question_specific_route_context_evidence_missing"],
        "tools": [],
    }

    prompt = build_recovery_prompt(
        run=run,
        compact_evidence=evidence,
        previous_output={"answer": "山體由花崗岩構成。"},
        verifier_errors=["unsupported_answer_despite_question_specific_evidence_gap"],
    )

    assert "unsupported_answer_despite_question_specific_evidence_gap" in prompt
    assert "工作區未提供" in prompt
    assert "deterministic_reference" not in prompt
    assert "allowed_decisions" not in prompt


def test_summary_requires_verifier_and_quality_acceptance(tmp_path: Path) -> None:
    base = {
        "context_identity_check": {"status": "pass"},
        "failure_category": None,
        "force": "NAV",
        "decision": "GO",
        "model_request_count": 1,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    results = [
        {
            **base,
            "question_id": "NAV-001",
            "verifier": {"status": "pass"},
            "answer_quality_screen": {
                "classification": "auto_screen_pass_requires_human_review"
            },
        },
        {
            **base,
            "question_id": "NAV-002",
            "verifier": {"status": "pass"},
            "answer_quality_screen": {"classification": "quality_fail"},
        },
        {
            **base,
            "question_id": "NAV-003",
            "verifier": {"status": "fail"},
            "answer_quality_screen": {"classification": "quality_needs_review"},
        },
    ]
    manifest = {
        "run_id": "test",
        "model": "qwen3:1.7b",
        "provider": "hailo_ollama_ai_hat_plus_2",
    }

    _write_summaries(tmp_path, manifest, results)

    summary = json.loads((tmp_path / "model_summary.json").read_text())
    assert summary["strict_answer_summary"] == {"accepted": 1, "rejected": 2}
    assert "strict verifier + quality acceptance: `1/3`" in (
        tmp_path / "summary.md"
    ).read_text()
