import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import ins_dr_field_movement_drill
from tools.ins_dr_field_movement_drill import run_field_movement_drill


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_field_movement_drill.py"


def test_field_movement_drill_dry_run_writes_plan(tmp_path: Path) -> None:
    mission_graph = tmp_path / "mission.json"
    mission_graph.write_text("{}\n", encoding="utf-8")

    report = run_field_movement_drill(
        output_dir=tmp_path / "drill",
        mission_graph_path=mission_graph,
        wheel_meters_per_tick=0.0042,
        dry_run_plan=True,
        pretty=True,
    )

    assert report["source"] == "ins_dr_field_movement_drill"
    assert report["dry_run_plan"] is True
    assert report["scout_ins_dr_navigation_completion_ready"] is False
    assert report["hardware_control_scope"] == "diagnostic_field_movement_drill_only"
    assert report["plan"]["drill_profile"] == "gnss_anchor_then_live_gpio_wheel_then_reanchor"
    assert report["plan"]["wheel"]["live_wheel_encoder_gpio_capture"] is True
    assert report["plan"]["wheel"]["meters_per_tick"] == 0.0042
    assert report["plan"]["phase1_safety_decision_change_allowed"] is False
    assert (tmp_path / "drill" / "field-movement-drill-report.json").exists()


def test_field_movement_drill_calls_field_session_with_live_gpio_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission_graph = tmp_path / "mission.json"
    mission_graph.write_text("{}\n", encoding="utf-8")

    def field_session(**kwargs):
        assert kwargs["output_dir"] == tmp_path / "drill" / "field-session"
        assert kwargs["mission_graph_path"] == mission_graph
        assert kwargs["gnss_watch_before_readiness"] is True
        assert kwargs["gnss_watch_stop_on"] == "valid_fix"
        assert kwargs["run_live_proof"] is True
        assert kwargs["grove_imu_heading_capture"] is True
        assert kwargs["live_wheel_encoder_gpio_capture"] is True
        assert kwargs["wheel_encoder_left_gpio"] == 20
        assert kwargs["wheel_encoder_right_gpio"] == 21
        assert kwargs["wheel_meters_per_tick"] == 0.0042
        assert kwargs["movement_window_seconds"] == kwargs["wheel_encoder_capture_duration_seconds"]
        return {
            "source": "ins_dr_field_session",
            "field_session_status": "ready_for_live_proof",
            "scout_ins_dr_navigation_status": "field_ready",
            "scout_ins_dr_navigation_completion_ready": True,
            "ins_dr_completion_failed_gate_names": [],
            "next_action_status": "complete",
        }

    monkeypatch.setattr(ins_dr_field_movement_drill, "run_field_session", field_session)

    report = run_field_movement_drill(
        output_dir=tmp_path / "drill",
        mission_graph_path=mission_graph,
        wheel_meters_per_tick=0.0042,
        wheel_encoder_capture_duration_seconds=0.5,
    )

    assert report["dry_run_plan"] is False
    assert report["scout_ins_dr_navigation_completion_ready"] is True
    assert report["field_session_report_json"] == str(tmp_path / "drill" / "field-session" / "field-session-report.json")
    assert report["failed_gate_names"] == []
    assert report["field_session_report"]["source"] == "ins_dr_field_session"


def test_field_movement_drill_cli_dry_run(tmp_path: Path) -> None:
    mission_graph = tmp_path / "mission.json"
    mission_graph.write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path / "drill"),
            "--mission-graph",
            str(mission_graph),
            "--wheel-meters-per-tick",
            "0.0042",
            "--dry-run-plan",
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["dry_run_plan"] is True
    assert report["next_action_status"] == "dry_run_plan"
