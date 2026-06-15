from __future__ import annotations

import json
from pathlib import Path

from scout_route_readiness_tool import (
    ROUTE_READINESS_OUTPUT_KIND,
    ROUTE_READINESS_TOOL_ID,
    assess_scout_route_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_route_readiness_fixture_delays_without_required_pretrip_reviews() -> None:
    result = assess_scout_route_readiness(
        PROJECT_ROOT,
        query="出發前 Go/No-Go 可以出發嗎？",
    )

    assert result["artifact_kind"] == ROUTE_READINESS_OUTPUT_KIND
    assert result["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert result["answerability"] == "route_readiness_missing_required_fields"
    assert result["decision"] == "DELAY"
    assert "user_experience_level" in result["missing_fields"]
    assert "user_goal" in result["missing_fields"]
    assert "transport_access_plan" in result["missing_fields"]
    assert "weather_review" in result["missing_fields"]
    assert "equipment_review" in result["missing_fields"]
    assert result["route_readiness"]["role"] == (
        "Pre-Trip Route Readiness / Departure Gate"
    )
    assert result["departure_gate"]["approval_granted"] is False
    assert result["departure_gate"]["hard_readiness_status"] == "ready"
    assert result["route_state"]["checkpoint_count"] == 124
    assert result["route_state"]["segment_count"] == 123
    assert result["weather_daylight_state"]["human_review_required"] is True
    assert result["boundary"]["runtime_handoff_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False
    package = result["pretrip_decision_package"]
    outputs = package["required_outputs"]
    assert package["candidate_only"] is True
    assert package["runtime_safety_truth"] is False
    assert outputs["pretrip_decision"] == "DELAY"
    assert len(outputs["top_risk_sources"]) == 3
    assert outputs["top_risk_sources"][0]["source"] == "required_pretrip_input"
    assert outputs["required_conditions"]
    assert outputs["cp_graph"]["checkpoint_count"] == 124
    assert outputs["cp_graph"]["segment_count"] == 123
    assert outputs["latest_turnaround"]["checkpoint_name"] == "雲海保線所"
    assert outputs["not_recommended_stop_points"]
    assert outputs["alternatives_or_short_routes"]
    assert outputs["pretrip_checklist"]
    assert outputs["residual_risk"]
    assert package["decision_limits"]["allowed"] is False
    assert package["decision_limits"]["buffer_cost_statement"]
    assert package["traceability"]["raw_payloads_embedded"] is False
    assert package["acceptance_coverage"]["explicit_decision"] is True


def test_route_readiness_changes_plan_when_latest_return_is_before_target_eta() -> None:
    result = assess_scout_route_readiness(
        PROJECT_ROOT,
        query="最晚回程接駁是 16:30，這個行程可以嗎？",
        latest_return_time="16:30",
        transport_access_plan="latest_return_user_provided",
    )

    assert result["answerability"] == "route_readiness_missing_required_fields"
    assert result["decision"] == "CHANGE_PLAN"
    assert "transport_access_plan" not in result["missing_fields"]
    deadline = result["readiness_governance"]["transport_deadline"]
    assert deadline["latest_return_time"] == "16:30"
    assert deadline["resolved_deadline"] == "2013-10-08T16:30:00+08:00"
    assert deadline["target_eta"] == "2013-10-08T18:28:50+08:00"
    assert deadline["conflict"] is True
    package = result["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "CHANGE_PLAN"
    assert package["required_outputs"]["top_risk_sources"][0]["source"] == (
        "transport_deadline"
    )
    assert result["decision_output"]["cost"]["latestReturnDeadline"] == (
        "2013-10-08T16:30:00+08:00"
    )
    assert result["decision_output"]["cost"]["targetEta"] == (
        "2013-10-08T18:28:50+08:00"
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_route_readiness_no_go_for_hard_readiness_blocker(tmp_path: Path) -> None:
    project_root = _ready_project(tmp_path, readiness_status="blocked")

    result = assess_scout_route_readiness(
        project_root,
        query="出發前是否出發？",
        user_experience_level="intermediate",
        user_goal="training",
        transport_access_plan="confirmed shuttle",
        team_slowest_basis_confirmed=True,
        departure_time_confirmed=True,
        weather_reviewed=True,
        daylight_reviewed=True,
        equipment_confirmed=True,
        remote_contact_confirmed=True,
    )

    assert result["answerability"] == "route_readiness_decision_available"
    assert result["decision"] == "NO_GO"
    assert "Hard readiness report contains blocker findings." in result[
        "readiness_governance"
    ]["critical_gaps"]
    assert result["departure_gate"]["approval_granted"] is False
    assert "runtime safety truth" in result["field_answer"]
    package = result["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "NO_GO"
    assert package["required_outputs"]["top_risk_sources"][0]["severity"] == "critical"
    assert package["required_outputs"]["not_recommended_stop_points"]
    assert package["decision_limits"]["allowed"] is False


def test_route_readiness_go_when_all_pretrip_inputs_are_reviewed(tmp_path: Path) -> None:
    project_root = _ready_project(tmp_path)

    result = assess_scout_route_readiness(
        project_root,
        query="出發前 Go/No-Go 可以出發嗎？",
        user_experience_level="intermediate",
        user_goal="training",
        transport_access_plan="confirmed shuttle",
        team_slowest_basis_confirmed=True,
        departure_time_confirmed=True,
        weather_reviewed=True,
        daylight_reviewed=True,
        equipment_confirmed=True,
        remote_contact_confirmed=True,
    )

    assert result["answerability"] == "route_readiness_decision_available"
    assert result["decision"] == "GO"
    assert result["missing_fields"] == []
    assert result["readiness_governance"]["critical_gaps"] == []
    assert result["readiness_governance"]["warning_gaps"] == []
    assert result["departure_gate"]["approval_granted"] is False
    assert "GO" in result["field_answer"]
    package = result["pretrip_decision_package"]
    outputs = package["required_outputs"]
    assert outputs["pretrip_decision"] == "GO"
    assert outputs["cp_graph"]["checkpoint_count"] == 2
    assert outputs["latest_turnaround"]["checkpoint_name"] == "CP 2"
    assert outputs["suggested_stop_points"]
    assert outputs["not_recommended_stop_points"] == []
    assert outputs["pretrip_checklist"]
    assert package["decision_limits"]["allowed"] is True
    assert package["acceptance_coverage"]["traceable_inputs_recorded"] is True


def test_route_readiness_conditions_family_photo_goal_even_when_reviewed(
    tmp_path: Path,
) -> None:
    project_root = _ready_project(tmp_path)

    result = assess_scout_route_readiness(
        project_root,
        query="親子拍攝目標，出發前 Go/No-Go 可以出發嗎？",
        user_experience_level="intermediate",
        user_goal="親子拍攝",
        transport_access_plan="confirmed shuttle",
        team_slowest_basis_confirmed=True,
        departure_time_confirmed=True,
        weather_reviewed=True,
        daylight_reviewed=True,
        equipment_confirmed=True,
        remote_contact_confirmed=True,
    )

    assert result["answerability"] == "route_readiness_decision_available"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["missing_fields"] == []
    profile = result["user_goal_profile"]
    assert set(profile["goals"]) == {"photo", "family"}
    assert profile["candidate_only"] is True
    assert profile["runtime_safety_truth"] is False
    assert profile["photo_or_social_goal"] is True
    assert profile["family_or_child_goal"] is True
    governance = result["readiness_governance"]
    assert any("拍攝" in gap for gap in governance["warning_gaps"])
    assert any("親子" in gap for gap in governance["warning_gaps"])
    package = result["pretrip_decision_package"]
    outputs = package["required_outputs"]
    assert outputs["pretrip_decision"] == "CONDITIONAL_GO"
    assert outputs["user_goal_profile"]["goal_labels"] == ["拍攝", "親子/家庭"]
    assert any(
        item["policy"] == "not_recommended_until_goal_limits_reviewed"
        for item in outputs["not_recommended_stop_points"]
    )
    assert any(
        item["policy"] == "not_recommended_until_family_controls_reviewed"
        for item in outputs["not_recommended_stop_points"]
    )
    assert package["decision_limits"]["allowed"] is True
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "可有條件進入人工出發門檢。"
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_route_readiness_output_kind_constant() -> None:
    assert ROUTE_READINESS_OUTPUT_KIND == "scout_ai_route_readiness_tool_output"


def _ready_project(tmp_path: Path, *, readiness_status: str = "ready") -> Path:
    project_root = tmp_path / "route_ready_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "route_ready_project",
                "readiness_report_ref": "outputs/readiness_report.json",
                "planned_eta_ref": "outputs/planned_eta.json",
                "resource_plan_ref": "outputs/resource_plan.json",
                "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
                "reviewed_package_ref": "outputs/pretrip_package.reviewed.json",
                "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "readiness_report.json").write_text(
        json.dumps(
            {
                "status": readiness_status,
                "findings": []
                if readiness_status == "ready"
                else [
                    {
                        "rule_id": "missing_retreat",
                        "severity": "blocker",
                        "message": "Retreat route missing.",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "planned_eta.json").write_text(
        json.dumps(
            {
                "assumption": {
                    "planned_start_time": "2026-05-01T06:00:00+08:00",
                    "target_eta": "2026-05-01T12:00:00+08:00",
                    "turn_back_checkpoint_eta": "2026-05-01T09:00:00+08:00",
                    "turn_back_checkpoint_node_name": "CP 2",
                    "team_multiplier_status": "derived_from_slowest_member",
                    "daylight_policy_status": "evaluated",
                },
                "estimates": [{"estimate_id": "eta.1"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "resource_plan.json").write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "device_id": "phone",
                        "readiness": "ready",
                        "review": {"review_state": "accepted"},
                    }
                ],
                "equipment": [
                    {
                        "equipment_id": "offline_map",
                        "readiness": "available",
                        "review": {"review_state": "accepted"},
                    }
                ],
                "team_members": [
                    {
                        "member_id": "leader",
                        "review": {"review_state": "accepted"},
                    }
                ],
                "remote_contact_plan": {
                    "review": {"review_state": "accepted"},
                    "secret_contact_details_included": False,
                },
                "emergency_plan": {
                    "review": {"review_state": "accepted"},
                    "secret_contact_details_included": False,
                },
                "departure_readiness_context": {
                    "blocker_candidates": [],
                    "warning_candidates": [],
                    "blocks_existing_eta_or_readiness": False,
                    "hard_readiness_mutation_allowed": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "weather_daylight_evidence.json").write_text(
        json.dumps(
            {
                "date": "2026-05-01",
                "timezone": "Asia/Taipei",
                "authoritative_weather_computed": True,
                "human_review_required": False,
                "validation": {"validation_status": "reviewed"},
                "weather_window": {"source_status": "reviewed", "hazard_notes": []},
                "daylight": {
                    "source_status": "reviewed",
                    "sunrise": "05:20",
                    "sunset": "18:30",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "pretrip_package.reviewed.json").write_text(
        json.dumps(
            {
                "package_id": "pretrip.route_ready_project.v0",
                "route_summary": {"route_name": "Demo Route"},
                "boundary": {
                    "departure_approval_granted": False,
                    "departure_gate_required_before_runtime": False,
                    "reviewed_package_is_not_departure_approval": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps(
            {
                "checkpoints": [{"checkpoint_id": "cp.start"}, {"checkpoint_id": "cp.1"}],
                "segments": [{"segment_id": "seg.1"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root
