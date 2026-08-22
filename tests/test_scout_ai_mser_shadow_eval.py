from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from tools.scout_ai_mser_shadow_eval import (
    EXPECTED_FORCE_RUN_DISTRIBUTION,
    ShadowCaseResult,
    ShadowRunManifest,
    ShadowSummary,
    build_parser,
    expand_shadow_runs,
    project_environment,
    resolve_total_info,
    run_eval,
)


def _scenario(rank: int) -> dict[str, object]:
    scenario_id = f"fixture.boss-approach.rank-{rank}.v1"
    return {
        "scenario_id": scenario_id,
        "source_mode": "synthetic_replay",
        "project_id": "fixture-project",
        "observed_at": "2026-07-24T08:00:00+00:00",
        "boss_point_id": f"boss-{rank}",
        "boss_rank": rank,
        "lat": 24.0 + (rank / 100),
        "lon": 121.0 + (rank / 100),
        "elevation_m": 2800.0 + rank,
        "horizontal_accuracy_m": 5.0,
        "fix_quality": "synthetic_route_interpolation",
        "route_progress_m": float(rank * 10_000),
        "distance_to_boss_along_route_m": 500.0,
        "nearest_cp_id": f"CP-{rank}",
        "nearest_cp_route_progress_m": float(rank * 10_000 - 100),
        "nearest_route_distance_m": 2.0,
        "heading_deg": 90.0,
        "travel_direction": "increasing_route_progress",
        "risk_terrain_candidate": {
            "risk_score": 40.0 + rank,
            "risk_bucket": "moderate",
            "exposure_risk": 0.35,
            "slip_risk": 0.4,
            "rockfall_risk": 0.25,
            "escape_cost": 0.45,
            "terrain_complexity": 0.5,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "source_refs": [
            {
                "role": "risk_ribbon",
                "path": "outputs/risk/risk_ribbon.geojson",
                "sha256": f"{rank}" * 64,
            },
            {
                "role": "route_summary",
                "path": "normalized/routes/route_summary.json",
                "sha256": "a" * 64,
            },
        ],
        "condition_overlay_refs": [],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _question(force: str, ordinal: int) -> str:
    stems = {
        "EXP": "這條路線有哪些歷史與自然脈絡？",
        "RPF": "以目前體力，今天能不能照原定腳程前進？",
        "PER": "這裡可以停十分鐘嗎？",
        "RTE": "這條路線應該怎麼規劃撤退點？",
        "WTH": "現在的天氣是否適合繼續前進？",
        "NAV": "我現在是否偏離原本路線？",
    }
    return f"{stems[force]}（fixture {ordinal}）"


def _case(force: str, ordinal: int, global_ordinal: int) -> dict[str, object]:
    scenario_id = f"fixture.boss-approach.rank-{((ordinal - 1) % 5) + 1}.v1"
    question_id = f"{force}-{ordinal:03d}"
    question = _question(force, ordinal)
    answer_mode = "decision" if force in {"PER", "WTH"} else "compound"
    return {
        "case_id": f"six600.{question_id}.{scenario_id}",
        "question_id": question_id,
        "global_ordinal": global_ordinal,
        "force_code": force,
        "force_name": force,
        "capability_name": f"{force} fixture capability",
        "force_ordinal": ordinal,
        "subsection": "fixture",
        "question_text": question,
        "question_source_ref": "fixture://six-forces-corpus",
        "question_record_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "scenario_id": scenario_id,
        "expected_evidence_contract": {
            "required_context": [
                "scenario_location",
                "workspace_total_info",
            ],
            "required_evidence": ["source_provenance"],
            "scenario_identity_match_required": True,
            "provenance_required": True,
            "freshness_required": force in {"RPF", "PER", "WTH", "NAV"},
            "route_intersection_required": force in {"PER", "RTE", "WTH", "NAV"},
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
            "answer_mode": answer_mode,
            "allowed_decisions": [
                "GO",
                "CONDITIONAL_GO",
                "GUIDED_ONLY",
                "CHANGE_PLAN",
                "DELAY",
                "NO_GO",
                "ESCALATE",
            ],
            "forbidden_claims": ["guaranteed safe"],
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _total_info(scenario_id: str) -> dict[str, object]:
    return {
        "artifact_kind": "assistant_workspace_total_info_context",
        "artifact_version": "assistant_workspace_total_info_context.v0",
        "project_id": "fixture-project",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "route_context": {
            "status": "available",
            "source_path": "normalized/routes/route_summary.json",
            "distance_m": 50_000.0,
        },
        "body_resource_context": {
            "status": "available",
            "source_path": "outputs/health/energy_vitals_snapshot.json",
            "observed_at": "2026-07-24T08:00:00+00:00",
            "fatigue_index": 0.35,
            "energy_reserve": 0.72,
            "cognitive_confidence": 0.82,
            "safety_margin": 0.7,
        },
        "communication_context": {
            "status": "available",
            "source_path": "outputs/communication/current_reachability.json",
            "observed_at": "2026-07-24T08:00:00+00:00",
            "communication_reliability": 0.8,
            "coverage_confidence": 0.75,
            "emergency_reachability": 0.78,
        },
        "mission_context": {
            "status": "available",
            "source_path": "outputs/mission/current_margin.json",
            "observed_at": "2026-07-24T08:00:00+00:00",
            "team_distance_m": 15.0,
            "remaining_daylight_minutes": 240.0,
            "mission_margin": 0.7,
            "shelter_reachability": 0.65,
        },
        "fixture_scenario_id": scenario_id,
    }


def _artifact() -> dict[str, object]:
    forces = ("EXP", "RPF", "PER", "RTE", "WTH", "NAV")
    scenarios = [_scenario(rank) for rank in range(1, 6)]
    cases = [
        _case(force, ordinal, (force_index * 100) + ordinal)
        for force_index, force in enumerate(forces)
        for ordinal in range(1, 101)
    ]
    return {
        "artifact_kind": "scout_ai_six_forces_boss_approach_scenarios",
        "artifact_version": "scout_ai_six_forces_boss_approach_scenarios.v1",
        "project_id": "fixture-project",
        "source_mode": "synthetic_replay",
        "scenarios": scenarios,
        "cases": cases,
        "total_info_by_scenario_id": {
            str(item["scenario_id"]): _total_info(str(item["scenario_id"]))
            for item in scenarios
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _write_fixture(workspace: Path) -> Path:
    path = workspace / "outputs/evals/six_forces_fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_artifact(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _args(
    workspace: Path,
    *,
    run_id: str,
    max_runs: int,
    resume: bool = False,
):
    values = [
        "--workspace",
        str(workspace),
        "--scenario-artifact",
        "outputs/evals/six_forces_fixture.json",
        "--run-id",
        run_id,
        "--max-runs",
        str(max_runs),
    ]
    if resume:
        values.append("--resume")
    return build_parser().parse_args(values)


def test_existing_six_forces_corpus_expands_to_expected_1000_run_distribution() -> None:
    runs = expand_shadow_runs(_artifact())

    assert len(runs) == 1000
    assert Counter(item["force_code"] for item in runs) == Counter(
        EXPECTED_FORCE_RUN_DISTRIBUTION
    )
    assert len({item["run_case_id"] for item in runs}) == 1000
    assert len({item["question_id"] for item in runs}) == 600


def test_resume_appends_only_unfinished_run_case_ids(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    run_dir = run_eval(
        _args(tmp_path, run_id="resume-fixture", max_runs=2),
    )
    resumed_dir = run_eval(
        _args(tmp_path, run_id="resume-fixture", max_runs=3, resume=True),
    )

    assert resumed_dir == run_dir
    rows = [
        json.loads(line)
        for line in (run_dir / "per_case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 3
    assert len({row["run_case_id"] for row in rows}) == 3
    manifest = ShadowRunManifest.model_validate_json(
        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    summary = ShadowSummary.model_validate_json(
        (run_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert manifest.resume is True
    assert manifest.selected_run_count == 3
    assert summary.completed_run_count == 3
    assert summary.duplicate_run_case_id_count == 0


def test_artifacts_expose_joinable_mser_shadow_schema(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    run_dir = run_eval(
        _args(tmp_path, run_id="schema-fixture", max_runs=4),
    )

    result_lines = (
        (run_dir / "per_case_results.jsonl").read_text(encoding="utf-8").splitlines()
    )
    results = [
        ShadowCaseResult.model_validate_json(line)
        for line in result_lines
        if line.strip()
    ]
    manifest = ShadowRunManifest.model_validate_json(
        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    summary = ShadowSummary.model_validate_json(
        (run_dir / "summary.json").read_text(encoding="utf-8")
    )

    assert len(results) == 4
    assert manifest.full_matrix_run_count == 1000
    assert manifest.provider_calls_made is False
    assert manifest.tools_executed is False
    assert summary.completed_run_count == 4
    for result in results:
        assert result.join_keys["run_case_id"] == result.run_case_id
        assert result.decision_type
        assert result.selected_dimensions is not None
        assert result.sufficiency["status"]
        assert "selected_tools" in result.tool_plan
        assert 0.0 <= result.compression["retained_signal_ratio"] <= 1.0
        assert result.provider_calls_made is False
        assert result.tools_executed is False
        assert result.candidate_only is True
        assert result.runtime_safety_truth is False


def test_weather_variants_remain_distinct_after_shared_projection(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    runs = [
        item
        for item in expand_shadow_runs(artifact)
        if item["question_id"] == "WTH-001"
    ]
    assert [item["variant_id"] for item in runs] == [
        "severe_fresh_route_intersecting",
        "benign_fresh_route_intersecting",
        "stale_unknown_weather",
    ]

    projected = {}
    for run in runs:
        total_info, _ = resolve_total_info(
            artifact=artifact,
            run=run,
            workspace=tmp_path,
        )
        representation, _ = project_environment(
            artifact=artifact,
            run=run,
            total_info=total_info,
            now=datetime.fromisoformat(run["scenario"]["observed_at"]),
        )
        projected[run["variant_id"]] = [
            signal
            for signal in representation.all_signals()
            if signal.dimension.value == "weather.stability"
        ]

    severe = projected["severe_fresh_route_intersecting"]
    benign = projected["benign_fresh_route_intersecting"]
    stale = projected["stale_unknown_weather"]
    assert len(severe) == len(benign) == len(stale) == 1
    assert severe[0].value < benign[0].value
    assert stale[0].availability.value == "stale"
