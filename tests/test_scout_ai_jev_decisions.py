"""Offline contract tests for the isolated Jev Decisions benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scout.nextgen.jev_decisions import (
    JEvEndpoint,
    JevChoiceAnswer,
    JevDecisionRequest,
    JevDecisionResponse,
    JevDecisionError,
    JevNoulAnswer,
    JevScoreAnswer,
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
    build_jev_benchmark_cases,
    build_jev_dataset,
    execute_deterministic_query_plan,
    run_jev_benchmark,
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


def _write_workspace(root: Path) -> None:
    project = _project_payload()
    project.update(
        {
            "checkpoint_candidates_ref": "checkpoints.json",
            "terrain_risk_candidates_ref": "terrain.json",
            "risk_ribbon_ref": "risk.geojson",
            "cwa_weather_evidence_ref": "weather.json",
            "contextual_permission_rules_ref": "permission.json",
        }
    )
    (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (root / "checkpoints.json").write_text(
        json.dumps([{"candidate_only": True} for _ in range(3)]),
        encoding="utf-8",
    )
    (root / "terrain.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "requires_human_review": True,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                    {
                        "requires_human_review": False,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "risk.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"risk_level": 1, "risk_bucket": "low"},
                    },
                    {
                        "type": "Feature",
                        "properties": {"risk_level": 3, "risk_bucket": "high"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "weather.json").write_text(
        json.dumps({"fetched_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    (root / "permission.json").write_text(
        json.dumps(
            {
                "plan_node_policies": [
                    {
                        "reviewed": False,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_workspace_projection_is_allowlisted_and_cases_are_ten() -> None:
    projection = build_anonymized_workspace_projection_from_payload(_project_payload())
    cases = build_jev_benchmark_cases(projection)
    dataset = build_jev_dataset(projection, cases)

    assert len(cases) == 10
    assert {case.family.value for case in cases} == {
        "workspace_dependency",
        "workspace_query_intent",
        "safety_boundary",
    }
    encoded = json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False)
    assert "/" not in encoded
    assert "project_id" not in encoded
    assert "runtime_safety_truth" in encoded
    assert dataset.candidate_only is True
    assert dataset.runtime_safety_truth is False


def build_anonymized_workspace_projection_from_payload(
    payload: dict[str, Any],
):
    """Keep the projection test independent from the user's large workspace."""

    # The production function reads project.json.  A temporary path is avoided
    # here so the test only exercises the public projection shape through the
    # same input contract in a small, deterministic fixture.
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
        return build_anonymized_workspace_projection(root)


def test_openrouter_transport_keeps_secret_out_of_payload() -> None:
    captured: dict[str, Any] = {}

    def transport(endpoint, payload, headers, timeout_seconds):
        captured.update(
            {
                "endpoint": endpoint,
                "payload": payload,
                "headers": headers,
                "timeout": timeout_seconds,
            }
        )
        return {
            "model": "typesafe/jev-1.13-20260917",
            "answers": {
                "ok": {"type": "noul", "noul": 0.99},
            },
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.0},
        }

    client = OpenRouterJevClient(
        api_key="secret-test-key",
        model_id="typesafe/jev-1.13",
        transport=transport,
    )
    request = JevDecisionRequest(
        model="typesafe/jev-1.13",
        state={"anonymous": True},
        questions={
            "ok": {
                "type": "noul",
                "instructions": "Is the state valid?",
                "criteria": {
                    "true": "The state is valid.",
                    "false": "The state is invalid.",
                },
            }
        },
    )

    response = client.decide(request)

    assert response.answers["ok"].noul == 0.99  # type: ignore[union-attr]
    assert captured["endpoint"] == JEvEndpoint
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    assert "secret-test-key" not in json.dumps(captured["payload"])


def test_openrouter_rejects_noul_without_explicit_criteria() -> None:
    client = OpenRouterJevClient(
        api_key="secret-test-key",
        model_id="typesafe/jev-1.13",
        transport=lambda *_args: {},
    )
    request = JevDecisionRequest(
        model="typesafe/jev-1.13",
        state={"anonymous": True},
        questions={
            "ok": {
                "type": "noul",
                "instructions": "Is the state valid?",
            }
        },
    )

    with pytest.raises(JevDecisionError, match="explicit true/false criteria"):
        client.decide(request)


def _response_for_case(case) -> JevDecisionResponse:
    answers: dict[str, Any] = {}
    for question_id, expected in case.expected.items():
        question = case.questions[question_id]
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
                legend={"0": "low", "1": "medium", "2": "high"},
                probabilities={"0": 0.0, "1": 0.0, "2": 1.0},
                confidence=1.0,
            )
        assert question.type == expected.type
    return JevDecisionResponse(
        model="test-model",
        answers=answers,
        usage={"input_tokens": 20, "output_tokens": 10, "cost": 0.0},
    )


class _FakeClient:
    def decide(self, request: JevDecisionRequest) -> JevDecisionResponse:
        assert request.model == "test-model"
        # The expected values are part of the offline fixture only; production
        # clients never receive this fake implementation.
        for case in _FAKE_CASES:
            if case.state == request.state:
                return _response_for_case(case)
        raise AssertionError("unknown test case")


def test_fake_jev_run_is_fully_typed_and_candidate_only(tmp_path: Path) -> None:
    projection = build_anonymized_workspace_projection_from_payload(_project_payload())
    cases = build_jev_benchmark_cases(projection)
    global _FAKE_CASES
    _FAKE_CASES = cases

    report = run_jev_benchmark(
        model_id="test-model",
        cases=cases,
        client=_FakeClient(),
        workspace_root=None,
    )

    assert report.disposition.value == "passed"
    assert report.metrics.passed_cases == 10
    assert report.metrics.decision_accuracy == 1.0
    assert report.metrics.critical_failures == 0
    assert report.candidate_only is True
    assert report.runtime_safety_truth is False


def test_deterministic_query_plans_use_real_workspace_service(tmp_path: Path) -> None:
    _write_workspace(tmp_path)

    expected = {
        "count-checkpoints": ("success", 3),
        "filter-terrain-risk": ("success", 1),
        "argmax-risk-profile": ("success", 1),
        "freshness-weather": ("warning", 1),
    }
    for plan, (status, count) in expected.items():
        result = execute_deterministic_query_plan(
            workspace_root=tmp_path,
            plan=plan,
        )
        assert result.status == status
        assert result.result_count == count
        assert result.passed is True
        assert result.candidate_only is True
        assert result.runtime_safety_truth is False
