from __future__ import annotations

from pathlib import Path

from scout_team_status_tool import (
    TEAM_STATUS_OUTPUT_KIND,
    TEAM_STATUS_TOOL_ID,
    assess_scout_team_status,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_team_status_reports_fixture_missing_live_team_fields() -> None:
    result = assess_scout_team_status(
        PROJECT_ROOT,
        query="後隊在哪？留守回報準備好了嗎？",
    )

    assert result["artifact_kind"] == TEAM_STATUS_OUTPUT_KIND
    assert result["tool_id"] == TEAM_STATUS_TOOL_ID
    assert result["answerability"] == "team_status_missing_required_fields"
    assert result["decision"] == "DELAY"
    assert "member_positions_or_last_heard" in result["missing_fields"]
    assert "communication_status" in result["missing_fields"]
    assert result["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert result["team_status"]["remote_contact"]["available"] is True
    assert result["team_status"]["remote_contact"]["review_state"] == "needs_review"
    assert "隊伍守門員" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["outbound_send_performed"] is False


def test_team_status_escalates_for_missing_teammate_and_overdue_checkin() -> None:
    result = assess_scout_team_status(
        PROJECT_ROOT,
        query="隊友不見，最後聯絡 55 分鐘前，要不要通知留守？",
        team_members=[
            {
                "member_id": "lead",
                "display_label": "Lead",
                "accounted_for": True,
                "last_heard_minutes": 5,
            },
            {
                "member_id": "tail",
                "display_label": "Tail",
                "accounted_for": False,
                "position_status": "missing",
                "last_heard_minutes": 55,
            },
        ],
        communication_status="no_signal",
        checkin_overdue_minutes=55,
        rendezvous_point="雲海保線所",
        all_accounted_for=False,
    )

    assert result["answerability"] == "team_status_decision_available"
    assert result["decision"] == "ESCALATE"
    assert "有隊員未確認位置或狀態。" in result["team_governance"][
        "critical_gaps"
    ]
    assert result["team_status_guardian"]["outbound_send_performed"] is False
    assert result["boundary"]["remote_outbound_send_allowed"] is False
    assert "不得自動通知留守人" in result["field_answer"]


def test_team_status_go_when_direct_team_inputs_are_ready(tmp_path: Path) -> None:
    project_root = tmp_path / "team_ready_project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        '{"project_id":"team_ready_project"}',
        encoding="utf-8",
    )

    result = assess_scout_team_status(
        project_root,
        query="隊伍都集合好了，可以照計畫走嗎？",
        team_members=[
            {
                "member_id": "lead",
                "display_label": "Lead",
                "accounted_for": True,
                "last_heard_minutes": 2,
            },
            {
                "member_id": "tail",
                "display_label": "Tail",
                "accounted_for": True,
                "last_heard_minutes": 4,
            },
        ],
        communication_status="ok",
        checkin_overdue_minutes=0,
        planned_checkin_interval_minutes=30,
        rendezvous_point="天池山莊",
        split_team=False,
        all_accounted_for=True,
    )

    assert result["answerability"] == "team_status_decision_available"
    assert result["decision"] == "GO"
    assert result["missing_fields"] == []
    assert result["team_governance"]["critical_gaps"] == []
    assert result["team_governance"]["warning_gaps"] == []
    assert "GO" in result["field_answer"]
    assert result["debug_sources"]["resource_plan_source"] is None


def test_team_status_output_kind_constant() -> None:
    assert TEAM_STATUS_OUTPUT_KIND == "scout_ai_team_status_tool_output"
