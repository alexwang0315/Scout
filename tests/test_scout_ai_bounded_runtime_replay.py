from __future__ import annotations

from pathlib import Path

from tools.scout_ai_bounded_runtime_replay import (
    DEFAULT_REPLAY_MAX_CONTEXT_CHARS,
    DeterministicProgressiveReplayRunner,
    compare_eval_reports,
    run_workspace_15k_join_replay,
)
from tools.scout_ai_live_tool_selection_eval import EvalCase, run_live_tool_selection_eval

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"


def test_replay_construction_defaults_do_not_add_scout_time_or_context_ceiling() -> None:
    runner = DeterministicProgressiveReplayRunner()

    assert runner._runner.workspace_model_max_tokens is None
    assert DEFAULT_REPLAY_MAX_CONTEXT_CHARS is None


def test_compare_eval_reports_uses_true_exact_match_and_micro_recall() -> None:
    before = {
        "case_count": 2,
        "model_usage_totals": {"requests": 6, "input_tokens": 120_000},
        "samples": [
            {
                "required_tool_ids": ["a", "b"],
                "model_native_tool_ids": ["a", "b", "extra"],
            },
            {
                "required_tool_ids": ["c"],
                "model_native_tool_ids": [],
            },
        ],
    }
    after = {
        "case_count": 2,
        "model_usage_totals": {"requests": 4, "input_tokens": 4_000},
        "agent_run_ledger_totals": {
            "tool_schema_chars": 1_200,
            "tool_result_chars": 900,
        },
        "samples": [
            {
                "required_tool_ids": ["a", "b"],
                "model_native_tool_ids": ["a", "b"],
                "agent_run_ledger": {"input_tokens": 1_800},
            },
            {
                "required_tool_ids": ["c"],
                "model_native_tool_ids": ["c"],
                "agent_run_ledger": {"input_tokens": 2_200},
            },
        ],
    }

    comparison = compare_eval_reports(before, after)

    assert comparison["before"]["exact_set_match_count"] == 0
    assert comparison["before"]["tool_recall_micro"] == 0.6667
    assert comparison["before"]["input_tokens_per_turn"] == 60_000
    assert comparison["after"]["exact_set_match_count"] == 2
    assert comparison["after"]["tool_recall_micro"] == 1.0
    assert comparison["after"]["input_tokens_per_turn"] == 2_000
    assert comparison["after"]["input_tokens_p95"] == 2_200
    assert comparison["delta"]["input_tokens_per_turn_reduction_ratio"] == 0.9667


def test_compare_eval_reports_prefers_complete_ledger_usage_for_failed_runs() -> None:
    report = {
        "case_count": 2,
        "model_usage_totals": {"requests": 1, "input_tokens": 100},
        "agent_run_ledger_totals": {
            "request_count": 4,
            "input_tokens": 4_000,
        },
        "samples": [
            {
                "required_tool_ids": [],
                "model_native_tool_ids": [],
                "agent_run_ledger": {"input_tokens": 1_500},
            },
            {
                "required_tool_ids": [],
                "model_native_tool_ids": [],
                "agent_run_ledger": {"input_tokens": 2_500},
            },
        ],
    }

    comparison = compare_eval_reports(report, report)

    assert comparison["after"]["input_tokens"] == 4_000
    assert comparison["after"]["input_tokens_per_turn"] == 2_000
    assert comparison["after"]["requests"] == 4


def test_deterministic_replay_uses_only_selected_schema_and_executes_tool() -> None:
    runner = DeterministicProgressiveReplayRunner()
    case = EvalCase(
        "route-count",
        "目前這條 route 有多少個 CP？",
        ("pydantic_ai.tool.search_scout_route_structure.v0",),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=runner,
        project_id="chilai_nanhua_day1",
        workspace_root=WORKSPACE_ROOT,
        timeout_seconds=10,
        max_context_chars=2_000,
    )

    sample = report["samples"][0]
    assert report["evaluation_semantics"] == (
        "deterministic_disclosed_tool_protocol_not_model_quality"
    )
    assert report["scoring_policy"]["calls_every_disclosed_tool"] is True
    assert sample["model_native_tool_ids"] == list(case.required_tool_ids)
    assert sample["exact_required_tool_set_match"] is True
    assert sample["agent_run_ledger"]["request_count"] <= 3
    assert sample["agent_run_ledger"]["domain_tool_schema_count"] == 1
    assert sample["agent_run_ledger"]["internal_composition_tool_schema_count"] == 1
    assert sample["agent_run_ledger"]["requests"][-1]["tool_schema_count"] == 0
    assert sample["answer_grounded"] is True
    assert sample["grounding_verification"]["passed"] is True
    assert sample["grounding_verification"]["rejected_draft_claim_count"] == 0
    assert sample["grounding_verification"]["unsupported_claim_count"] == 0


def test_deterministic_replay_clones_fresh_runner_state_per_case() -> None:
    runner = DeterministicProgressiveReplayRunner()
    runner._runner.last_workspace_tool_invocations = [{"tool_id": "stale"}]

    clone = runner.clone_for_isolated_run()

    assert clone is not runner
    assert clone._runner is not runner._runner
    assert clone.last_workspace_tool_invocations == []


def test_replay_can_execute_registered_route_architecture_bundle() -> None:
    runner = DeterministicProgressiveReplayRunner()
    case = EvalCase(
        "route-architecture",
        "路線結構資料中的 route summary 起點、終點與 bbox 座標是多少？",
        (
            "pydantic_ai.tool.search_scout_route_structure.v0",
            "scout.ai.route_architecture.assess.v0",
        ),
    )

    report = run_live_tool_selection_eval(
        cases=(case,),
        runner=runner,
        project_id="chilai_nanhua_day1",
        workspace_root=WORKSPACE_ROOT,
        timeout_seconds=10,
        max_context_chars=2_000,
    )

    sample = report["samples"][0]
    assert set(sample["model_native_tool_ids"]) == set(case.required_tool_ids)
    assert sample["exact_required_tool_set_match"] is True
    assert sample["agent_run_ledger"]["domain_tool_schema_count"] == 2
    assert sample["agent_run_ledger"]["internal_composition_tool_schema_count"] == 1


def test_15k_join_replay_proves_full_evidence_chain(tmp_path: Path) -> None:
    project_root = tmp_path / "route_project"
    candidates = project_root / "candidates"
    candidates.mkdir(parents=True)
    (project_root / "project.json").write_text(
        """{
  "project_id": "route_project",
  "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
  "checkpoint_candidates_ref": "candidates/checkpoints.json"
}\n""",
        encoding="utf-8",
    )
    (candidates / "route_mileage_k_anchors.json").write_text(
        """{
  "anchor_count": 1,
  "anchors": [{
    "candidate_id": "route.anchor.15K",
    "display_label": "15K",
    "mileage_m": 15000.0,
    "lat": 24.034234788,
    "lon": 121.280180449,
    "candidate_only": true,
    "runtime_safety_truth": false
  }]
}\n""",
        encoding="utf-8",
    )
    (candidates / "checkpoints.json").write_text(
        """[
  {
    "candidate_id": "cp.128",
    "label": "CP 128",
    "lat": 24.0320,
    "lon": 121.2792,
    "candidate_only": true,
    "runtime_safety_truth": false
  },
  {
    "candidate_id": "cp.129",
    "label": "CP 129",
    "lat": 24.0500,
    "lon": 121.2900,
    "candidate_only": true,
    "runtime_safety_truth": false
  }
]\n""",
        encoding="utf-8",
    )

    report = run_workspace_15k_join_replay(project_root)

    assert report["status"] == "completed"
    assert report["prototype_status"] == "WORKING PROTOTYPE"
    assert report["budget"]["max_tool_calls"] == 10
    assert report["budget"]["max_model_requests"] == 10
    assert report["ledger"]["tool_call_count"] == 10
    assert report["ledger"]["request_count"] <= 10
    assert [item["stage"] for item in report["call_trace"]] == [
        "search",
        "drilldown",
        "filter",
        "aggregation",
        "drilldown",
        "join",
        "contradiction_check",
        "freshness_check",
        "freshness_check",
        "source_verification",
    ]
    assert report["grounding_verification"]["passed"] is True
    assert "15K" in report["answer"]
    assert "cp.128" in report["answer"]
    assert "candidates/route_mileage_k_anchors.json" in report["answer"]
    assert "candidates/checkpoints.json" in report["answer"]
    assert report["tool_repair"]["performed"] is False
    assert report["model_switch"]["performed"] is False
    assert report["codex_review"]["performed"] is False
    assert report["known_issues"] == []
