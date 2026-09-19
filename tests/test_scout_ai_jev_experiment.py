"""Focused tests for the Scout-owned Jev decision experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scout.nextgen.jev_decision_service import (
    JevDecisionService,
    JevEscalationDisposition,
    JevExperimentMode,
    JevFailureCategory,
    build_jev_experiment_cases,
    build_jev_experiment_dataset,
    run_jev_experiment,
)
from scout.nextgen.jev_decisions import (
    JevChoiceAnswer,
    JevDecisionResponse,
    JevNoulAnswer,
    JevScoreAnswer,
    build_anonymized_workspace_projection,
)


def _project_payload() -> dict[str, Any]:
    return {
        "source_artifact_count": 2,
        "checkpoint_candidate_count": 3,
        "segment_candidate_count": 4,
        "risk_score_point_count": 5,
        "risk_ribbon_segment_count": 6,
        "contextual_permission_rule_count": 2,
        "review_queue_item_count": 1,
        "human_review_count": 0,
        "route_context_point_count": 2,
        "cwa_rain_observation_count": 3,
        "cwa_weather_point_count": 4,
        "terrain_workspace_dem_status": "ready",
        "environment_risk_derivative_status": "ready_with_data_gaps",
        "cwa_cacheable": False,
        "cwa_ttl_seconds": 0,
        "cwa_rainfall_grid_ttl_seconds": 0,
        "osm_pbf_refresh_required": True,
        "actual_user_track_available": False,
        "cwa_external_api_calls_made": True,
        "risk_score_operational": False,
    }


def _projection(tmp_path: Path):
    (tmp_path / "project.json").write_text(
        json.dumps(_project_payload()),
        encoding="utf-8",
    )
    return build_anonymized_workspace_projection(tmp_path)


def _response(case, *, model: str = "test-model") -> JevDecisionResponse:
    answers: dict[str, Any] = {}
    for question_id, expected in case.expected.items():
        if expected.expected_choice is not None:
            answers[question_id] = JevChoiceAnswer(
                type="choice",
                choice=expected.expected_choice,
                probabilities={expected.expected_choice: 1.0},
                confidence=1.0,
            )
        elif expected.expected_noul is not None:
            answers[question_id] = JevNoulAnswer(
                type="noul",
                noul=1.0 if expected.expected_noul else 0.0,
            )
        else:
            answers[question_id] = JevScoreAnswer(
                type="score",
                score=expected.expected_score,
                legend={"0": "low", "1": "high"},
                probabilities={"0": 0.0, "1": 1.0},
                confidence=1.0,
            )
    return JevDecisionResponse(
        model=model,
        answers=answers,
        usage={"input_tokens": 100, "output_tokens": 50, "cost": 0.001},
    )


class _FakeClient:
    def __init__(self, cases) -> None:
        self.cases = cases
        self.calls = 0

    def decide(self, request):
        self.calls += 1
        case = next(case for case in self.cases if case.state == request.state)
        return _response(case, model=request.model)


def test_dataset_has_22_cases_and_only_compact_candidate_payload(tmp_path: Path) -> None:
    projection = _projection(tmp_path)
    cases = build_jev_experiment_cases(projection)
    dataset = build_jev_experiment_dataset(projection, cases)

    assert len(cases) == 22
    assert {case.question_class.value for case in cases} == {
        "static_fact",
        "aggregate",
        "spatial",
        "cross_artifact_join",
        "unsupported_ambiguous",
        "recovery",
    }
    encoded = json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False)
    assert "/home/" not in encoded
    assert "workspace_path" not in encoded
    assert '"latitude"' not in encoded
    assert '"longitude"' not in encoded
    assert dataset.candidate_only is True
    assert dataset.runtime_safety_truth is False


def test_fast_lane_and_mser_hard_gate(tmp_path: Path) -> None:
    projection = _projection(tmp_path)
    cases = build_jev_experiment_cases(projection)
    service = JevDecisionService()

    static_case = next(
        case for case in cases if case.question_class.value == "static_fact"
    )
    static_result = service.evaluate_case(
        case=static_case,
        mode=JevExperimentMode.ACTIVE,
        response=_response(static_case),
    )
    assert static_result.fast_lane is True
    assert static_result.jev_called is False
    assert static_result.model_request_count == 0
    assert static_result.final_disposition is JevEscalationDisposition.AUTO

    stale_case = next(case for case in cases if "stale-weather" in case.case_id)
    stale_response = _response(stale_case)
    stale_response = stale_response.model_copy(
        update={
            "answers": {
                **stale_response.answers,
                "evidence_sufficient": JevNoulAnswer(type="noul", noul=1.0),
                "escalation": JevChoiceAnswer(
                    type="choice",
                    choice="auto",
                    probabilities={"auto": 1.0},
                    confidence=1.0,
                ),
            }
        }
    )
    stale_result = service.evaluate_case(
        case=stale_case,
        mode=JevExperimentMode.ACTIVE,
        response=stale_response,
    )
    assert stale_result.final_disposition is JevEscalationDisposition.COLLECT_MORE_EVIDENCE
    assert stale_result.critical_safety_boundary_violation is False
    assert stale_result.failure_category is JevFailureCategory.MISSING_EVIDENCE


def test_low_risk_jev_more_evidence_signal_is_recorded_but_not_authoritative(
    tmp_path: Path,
) -> None:
    projection = _projection(tmp_path)
    case = next(case for case in build_jev_experiment_cases(projection) if "spatial-terrain-profile" in case.case_id)
    response = _response(case).model_copy(
        update={
            "answers": {
                **_response(case).answers,
                "evidence_sufficient": JevNoulAnswer(type="noul", noul=0.0),
                "escalation": JevChoiceAnswer(
                    type="choice",
                    choice="collect_more_evidence",
                    probabilities={"collect_more_evidence": 1.0},
                    confidence=1.0,
                ),
            }
        }
    )
    result = JevDecisionService().evaluate_case(
        case=case,
        mode=JevExperimentMode.ACTIVE,
        response=response,
    )
    assert result.mser_status.value == "sufficient"
    assert result.final_disposition is JevEscalationDisposition.AUTO
    assert result.over_escalation is True
    assert result.actual_deterministic_route.value == "GIS_spatial"

    stronger_response = _response(case).model_copy(
        update={
            "answers": {
                **_response(case).answers,
                "escalation": JevChoiceAnswer(
                    type="choice",
                    choice="use_stronger_model",
                    probabilities={"use_stronger_model": 1.0},
                    confidence=1.0,
                ),
            }
        }
    )
    stronger_result = JevDecisionService().evaluate_case(
        case=case,
        mode=JevExperimentMode.ACTIVE,
        response=stronger_response,
    )
    assert stronger_result.final_disposition is JevEscalationDisposition.AUTO
    assert stronger_result.over_escalation is True

    max_case = next(case for case in build_jev_experiment_cases(projection) if case.synthesis_failed)
    max_result = JevDecisionService().evaluate_case(
        case=max_case,
        mode=JevExperimentMode.ACTIVE,
        response=_response(max_case),
    )
    assert max_result.final_disposition is JevEscalationDisposition.USE_STRONGER_MODEL


def test_jev_cannot_control_deterministic_route(tmp_path: Path) -> None:
    projection = _projection(tmp_path)
    case = next(case for case in build_jev_experiment_cases(projection) if "spatial-terrain-profile" in case.case_id)
    response = _response(case).model_copy(
        update={
            "answers": {
                **_response(case).answers,
                "tool_family": JevChoiceAnswer(
                    type="choice",
                    choice="workspace_query",
                    probabilities={"workspace_query": 1.0},
                    confidence=1.0,
                ),
            }
        }
    )
    result = JevDecisionService().evaluate_case(
        case=case,
        mode=JevExperimentMode.ACTIVE,
        response=response,
    )
    assert result.actual_deterministic_route.value == "GIS_spatial"
    assert result.failure_category is JevFailureCategory.WRONG_ARTIFACT_TOOL_ROUTE
    assert result.critical_safety_boundary_violation is False


def test_comparison_runs_one_batched_request_only_for_non_fast_cases(
    tmp_path: Path,
) -> None:
    projection = _projection(tmp_path)
    cases = build_jev_experiment_cases(projection)
    client = _FakeClient(cases)
    dataset = build_jev_experiment_dataset(projection, cases)

    report = run_jev_experiment(
        model_id="test-model",
        cases=cases,
        client=client,
        dataset_hash=dataset.dataset_hash,
        workspace_projection_hash=projection.projection_hash,
    )

    assert client.calls == 17
    assert {mode.mode for mode in report.mode_reports} == {
        JevExperimentMode.BASELINE,
        JevExperimentMode.SHADOW,
        JevExperimentMode.ACTIVE,
    }
    baseline = next(
        mode for mode in report.mode_reports if mode.mode is JevExperimentMode.BASELINE
    )
    shadow = next(
        mode for mode in report.mode_reports if mode.mode is JevExperimentMode.SHADOW
    )
    active = next(
        mode for mode in report.mode_reports if mode.mode is JevExperimentMode.ACTIVE
    )
    assert baseline.metrics.total_model_requests == 0
    assert shadow.metrics.total_model_requests == 17
    assert active.metrics.total_model_requests == 17
    assert active.metrics.critical_safety_boundary_violations == 0
    assert active.metrics.passed_cases == 22
    assert report.candidate_only is True
    assert report.runtime_safety_truth is False


def test_unavailable_jev_fails_closed_for_eligible_cases(tmp_path: Path) -> None:
    projection = _projection(tmp_path)
    cases = build_jev_experiment_cases(projection)
    dataset = build_jev_experiment_dataset(projection, cases)
    report = run_jev_experiment(
        model_id="test-model",
        cases=cases,
        client=None,
        dataset_hash=dataset.dataset_hash,
        workspace_projection_hash=projection.projection_hash,
    )
    active = next(
        mode for mode in report.mode_reports if mode.mode is JevExperimentMode.ACTIVE
    )
    assert active.metrics.critical_safety_boundary_violations == 0
    assert all(
        result.final_disposition is not JevEscalationDisposition.AUTO
        for result in active.case_results
        if result.jev_called and not result.case_id.startswith("recovery-max")
    )
