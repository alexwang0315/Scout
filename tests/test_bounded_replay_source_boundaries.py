"""Replay policy and evidence rejection, with entirely synthetic local fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import assistant_pydantic_provider as provider
from scout.services.bounded_agent_runtime import BoundedAgentRuntime
from tools.scout_ai_bounded_runtime_replay import (
    DeterministicProgressiveReplayRunner,
    run_workspace_15k_join_replay,
)


def test_replay_keeps_offline_identity_and_ignores_external_model_environment(monkeypatch):
    monkeypatch.setenv("SCOUT_AI_ASSISTANT_MODEL", "openrouter:example/unused")
    monkeypatch.setenv("SCOUT_AI_OS_MODEL", "openrouter:example/unused")
    runner = DeterministicProgressiveReplayRunner()
    assert runner.model_name == "offline:deterministic-progressive-disclosure-replay"
    assert runner._runner.model_policy.requires_network is False
    assert runner.evaluation_semantics == "deterministic_disclosed_tool_protocol_not_model_quality"
    assert runner._runner.workspace_model_max_tokens is None


@pytest.mark.parametrize("fail", [False, True])
def test_replay_restores_model_factory_after_success_or_failure(monkeypatch, fail):
    runner = DeterministicProgressiveReplayRunner()
    factory = provider.build_chat_model
    labels = []

    def execution(*args, **kwargs):
        model = provider.build_chat_model(model_name="local")
        labels.append(model.model_name)
        if fail:
            raise RuntimeError("synthetic replay failure")
        return "synthetic replay result"

    monkeypatch.setattr(runner._runner, "run_with_workspace_tools", execution)
    if fail:
        with pytest.raises(RuntimeError, match="synthetic replay failure"):
            runner.run_with_workspace_tools("fixture", timeout_seconds=10, tool_context=object())
    else:
        assert runner.run_with_workspace_tools(
            "fixture", timeout_seconds=10, tool_context=object()
        ) == "synthetic replay result"
    assert labels == [runner.model_name]
    assert provider.build_chat_model is factory


@pytest.fixture(params=[(24.034234788, 121.280180449), (23.175326119, 120.788312733)])
def observed_join(tmp_path: Path, monkeypatch, request):
    lat, lon = request.param
    project = tmp_path / "synthetic_project"
    candidates = project / "candidates"
    candidates.mkdir(parents=True)
    documents = {
        "project.json": {
            "project_id": "synthetic_project",
            "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
        },
        "candidates/route_mileage_k_anchors.json": {
            "anchor_count": 1,
            "anchors": [{
                "candidate_id": "route.anchor.15K", "display_label": "15K",
                "mileage_m": 15000.0, "lat": lat, "lon": lon,
                "candidate_only": True, "runtime_safety_truth": False,
            }],
        },
        "candidates/checkpoints.json": [
            {"candidate_id": "cp.128", "label": "CP 128", "lat": lat + .001,
             "lon": lon, "candidate_only": True, "runtime_safety_truth": False},
            {"candidate_id": "cp.129", "label": "CP 129", "lat": lat + .1,
             "lon": lon + .1, "candidate_only": True, "runtime_safety_truth": False},
        ],
    }
    for relative, value in documents.items():
        (project / relative).write_text(json.dumps(value), encoding="utf-8")
    observed = []
    verify = BoundedAgentRuntime.verify_synthesis

    def capture(answer, *, evidence_cards):
        observed.append((answer, evidence_cards))
        return verify(answer, evidence_cards=evidence_cards)

    monkeypatch.setattr(BoundedAgentRuntime, "verify_synthesis", staticmethod(capture))
    report = run_workspace_15k_join_replay(project)
    assert len(observed) == 1
    return lat, lon, report, observed[0], verify


def test_join_binds_coordinates_to_the_actual_anchor_evidence(observed_join):
    lat, lon, report, _, _ = observed_join
    assert report["status"] == "completed"
    assert f"{lat:.9f}, {lon:.9f}" in report["answer"]
    assert "cp.128" in report["answer"]
    assert report["source_verification"]["passed"] is True
    assert report["grounding_verification"]["passed"] is True
    assert report["ledger"]["tool_call_count"] == 10
    assert len(report["call_trace"]) == 10
    assert report["evaluation_semantics"] == "faithful_deterministic_workspace_replay_not_model_quality"


@pytest.mark.parametrize("corruption", ["coordinate", "checkpoint", "citation", "safety_claim"])
def test_join_evidence_still_rejects_unsupported_answers(observed_join, corruption):
    lat, lon, report, captured, verify = observed_join
    answer, cards = captured
    assert report["grounding_verification"]["passed"] is True
    if corruption == "coordinate":
        altered = answer.replace(f"{lat:.9f}", f"{lat + .25:.9f}")
    elif corruption == "checkpoint":
        altered = answer.replace("cp.128", "cp.404")
    elif corruption == "citation":
        altered = answer.replace("candidates/route_mileage_k_anchors.json", "candidates/nonexistent.json")
    else:
        altered = answer + "此路線現在安全且可以出發 [candidates/route_mileage_k_anchors.json]。"
    assert altered != answer
    verdict = verify(altered, evidence_cards=cards)
    assert verdict.passed is False
