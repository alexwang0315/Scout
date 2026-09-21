"""Focused contract tests for the full Six-Forces Jev preflight."""

from __future__ import annotations

import json
from pathlib import Path

from scout.nextgen.jev_decisions import build_anonymized_workspace_projection
from scout.nextgen.jev_six_forces import build_six_forces_jev_request


def _projection(tmp_path: Path):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    return build_anonymized_workspace_projection(tmp_path)


def test_six_forces_jev_request_is_bounded_and_carries_mser_state(
    tmp_path: Path,
) -> None:
    request, metadata = build_six_forces_jev_request(
        model_id="typesafe/jev-1.13",
        projection=_projection(tmp_path),
        run={
            "question_text": "請評估目前路線的天候風險。",
            "force_code": "WTH",
            "scenario_id": "scenario-1",
            "variant_id": "base",
        },
        mser_context={
            "sufficiency": {
                "status": "insufficient",
                "information_needs": [{"dimension": "weather"}],
            }
        },
        compact_evidence={
            "tools": [
                {
                    "tool_id": "scout.weather.v1",
                    "status": "ok",
                    "answerability": "partial",
                    "missing_fields": ["freshness"],
                }
            ],
            "missing_evidence": ["freshness"],
        },
        deterministic_tool_ids=["scout.weather.v1"],
    )

    encoded = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
    assert len(request.questions) == 9
    assert metadata.mser_certificate["status"] == "insufficient"
    assert metadata.mser_certificate["information_need"] is True
    assert "question_contract" in request.state
    assert request.state["question_contract"]["artifact_family"] == "weather"
    assert request.state["candidate_only"] is True
    assert request.state["runtime_safety_truth"] is False
    assert "/home/" not in encoded
    assert "latitude" not in encoded
    assert "longitude" not in encoded
