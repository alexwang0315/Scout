from __future__ import annotations

from pathlib import Path

from scout_safety_action import build_shelter_direction


REPO_ROOT = Path(__file__).resolve().parents[1]
CHILAI_PROJECT = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_shelter_direction_ranks_local_candidate_targets_without_runtime_truth() -> None:
    result = build_shelter_direction(
        project_root=CHILAI_PROJECT,
        position={
            "lat": 24.0300,
            "lon": 121.2840,
            "source": "fixture_client_position",
        },
        query="目前氣候不好，我需要隱蔽，幫我指出方向",
        ttl_seconds=300,
    )

    assert result["artifact_kind"] == "scout_safety_action_shelter_direction"
    assert result["status"] == "completed"
    assert result["recommended_target"]["target_id"]
    assert result["recommended_target"]["distance_m"] > 0
    assert result["recommended_target"]["relative_direction"]
    assert result["ttl_seconds"] == 300
    assert result["text_zh"].startswith("建議往")
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["live_safety_api_calls_allowed"] is False
    assert result["boundary"]["phase1_safety_mutation_allowed"] is False
    assert any("candidate-only" in item for item in result["uncertainty_reasons"])
