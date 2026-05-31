import json
from pathlib import Path

import pytest

from tools import ins_dr_field_session
from tools.ins_dr_field_session import run_field_session
from tools.pi_hiwonder_imu_usb_smoke import parse_raw_hex_frames


def test_field_session_stops_before_live_proof_when_readiness_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(False))

    def fail_live_proof(**kwargs):
        raise AssertionError("live proof must not run when readiness is not ready")

    monkeypatch.setattr(ins_dr_field_session, "run_live_field_proof", fail_live_proof)

    report = run_field_session(
        output_dir=tmp_path,
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
        pretty=True,
    )

    assert report["field_session_status"] == "readiness_not_ready"
    assert report["scout_ins_dr_navigation_status"] == "not_ready_readiness"
    assert report["scout_ins_dr_navigation_completion_ready"] is False
    assert report["ins_dr_completion_gate_summary"]["overall_status"] == "not_ready_readiness"
    assert _gate(report, "gnss_anchor")["passed"] is False
    assert report["session_status"] == "readiness_not_ready"
    assert report["ready_for_live_field_proof"] is False
    assert report["completion_ready"] is False
    assert report["live_report"] is None
    assert report["hardware_control_scope"] == "diagnostic_field_session_orchestration_only"
    assert Path(report["gnss_hardware_snapshot_json"]).exists()
    assert Path(report["gnss_diagnosis_report_json"]).exists()
    assert Path(report["gnss_diagnosis_report_md"]).exists()
    assert Path(report["readiness_report_json"]).exists()
    assert (tmp_path / "field-session-report.json").exists()


def test_field_session_surfaces_gnss_command_path_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "collect_snapshot", lambda **kwargs: _snapshot_with_command_response())
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(False))

    report = run_field_session(
        output_dir=tmp_path,
        mission_graph_path=tmp_path / "mission.json",
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
        pretty=True,
    )

    command = report["gnss_command_path_summary"]
    assert command["command_path_proven"] is True
    assert command["receiver_response_observed_count"] == 1
    assert command["mon_hw_seen_count"] == 0
    assert command["targets"][0]["antenna_text_status"] == "OK"
    assert report["next_action"]["gnss_command_path_summary"] == command
    assert _gate(report, "gnss_anchor")["evidence"]["command_path_proven"] is True
    assert "GNSS Command/RF Debug" in Path(report["next_action_md"]).read_text(encoding="utf-8")


def test_field_session_reports_ready_without_running_live_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))

    def fail_live_proof(**kwargs):
        raise AssertionError("live proof must be opt-in")

    monkeypatch.setattr(ins_dr_field_session, "run_live_field_proof", fail_live_proof)
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path,
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=False,
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["field_session_status"] == "ready_for_live_proof"
    assert report["scout_ins_dr_navigation_status"] == "ready_for_live_proof"
    assert report["ins_dr_completion_failed_gate_names"] == ["live_field_proof"]
    assert _gate(report, "gnss_anchor")["passed"] is True
    assert _gate(report, "raw_imu_heading")["passed"] is True
    assert _gate(report, "wheel_odometry")["passed"] is True
    assert _gate(report, "live_field_proof")["status"] == "not_run"
    assert report["ready_for_live_field_proof"] is True
    assert report["completion_ready"] is False
    assert report["live_report"] is None


def test_field_session_runs_live_proof_with_readiness_selected_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")
    calls: list[dict] = []

    def live_proof(**kwargs):
        calls.append(kwargs)
        assert kwargs["readiness_report_json_path"] == tmp_path / "field-readiness-report.json"
        assert kwargs["gnss_port"] == "auto"
        assert kwargs["gnss_baud"] == 115200
        assert kwargs["heading_evidence_jsonl_paths"] == [imu_jsonl]
        assert kwargs["wheel_odometry_jsonl_paths"] == [wheel_jsonl]
        assert kwargs["wheel_provider"] == "scout_wheel_encoder"
        assert kwargs["allow_overwrite"] is True
        return {
            "source": "ins_dr_live_field_proof",
            "completion_ready": True,
            "live_field_proof_report_json": str(tmp_path / "live-field-proof" / "live-field-proof-report.json"),
        }

    monkeypatch.setattr(ins_dr_field_session, "run_live_field_proof", live_proof)

    report = run_field_session(
        output_dir=tmp_path,
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
        allow_overwrite=True,
    )

    assert len(calls) == 1
    assert report["field_session_status"] == "live_proof_completed"
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["scout_ins_dr_navigation_completion_ready"] is True
    assert report["ins_dr_completion_failed_gate_names"] == []
    assert report["ins_dr_completion_gate_summary"]["completion_ready"] is True
    assert all(gate["passed"] is True for gate in report["ins_dr_completion_gate_summary"]["gates"])
    assert report["completion_ready"] is True
    assert report["ins_dr_live_inputs_ready"] is True
    assert report["raw_imu_heading_evidence_summary"]["raw_imu_heading_ready"] is True
    assert report["wheel_odometry_input_summary"]["wheel_odometry_ready"] is True
    assert report["live_field_proof_report_json"] == str(
        tmp_path / "live-field-proof" / "live-field-proof-report.json"
    )


def test_field_session_blocks_live_proof_when_dr_inputs_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))

    def fail_live_proof(**kwargs):
        raise AssertionError("live proof must not run without raw IMU heading and wheel odometry evidence")

    monkeypatch.setattr(ins_dr_field_session, "run_live_field_proof", fail_live_proof)

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["field_session_status"] == "dr_inputs_not_ready"
    assert report["scout_ins_dr_navigation_status"] == "not_ready_dr_inputs"
    assert report["ins_dr_completion_failed_gate_names"] == [
        "raw_imu_heading",
        "wheel_odometry",
        "live_field_proof",
    ]
    assert _gate(report, "gnss_anchor")["passed"] is True
    assert _gate(report, "raw_imu_heading")["status"] == "missing_raw_imu_heading"
    assert _gate(report, "wheel_odometry")["status"] == "missing_wheel_odometry"
    assert _gate(report, "live_field_proof")["status"] == "waiting_for_required_inputs"
    assert report["ready_for_live_field_proof"] is True
    assert report["ins_dr_live_inputs_ready"] is False
    assert report["next_action_status"] == "collect_dr_evidence_inputs"
    assert "raw IMU heading baseline missing" in report["next_action"]["blockers"][0]
    assert Path(report["wheel_odometry_template_jsonl"]).exists()
    assert Path(report["wheel_odometry_template_md"]).exists()
    assert report["next_action"]["wheel_odometry_template_jsonl"] == report["wheel_odometry_template_jsonl"]
    assert "Wheel Odometry Template" in Path(report["next_action_md"]).read_text(encoding="utf-8")
    assert report["live_report"] is None


def test_field_session_rejects_dry_run_wheel_odometry_for_dr_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")
    wheel_jsonl = tmp_path / "wheel-dry-run.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {"timestamp_s": 10.0, "dry_run": True, "odometry": {"cumulative_distance_m": 0.0}},
                {"timestamp_s": 11.0, "dry_run": True, "odometry": {"cumulative_distance_m": 1.0}},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    summary = report["wheel_odometry_input_summary"]
    assert summary["wheel_odometry_ready"] is False
    assert summary["dry_run_payload_count"] == 2
    assert summary["missing_reason"] == "wheel_odometry_dry_run_only"
    assert _gate(report, "wheel_odometry")["passed"] is False


def test_field_session_can_capture_gpio_wheel_encoder_for_dr_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    monkeypatch.setattr(
        ins_dr_field_session,
        "capture_wheel_encoder_records",
        lambda **kwargs: [
            {"timestamp_s": 10.0, "dry_run": False, "odometry": {"cumulative_distance_m": 0.0}},
            {"timestamp_s": 11.0, "dry_run": False, "odometry": {"cumulative_distance_m": 1.0}},
        ],
    )
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_encoder_gpio_capture=True,
        wheel_meters_per_tick=0.05,
        wheel_encoder_capture_duration_seconds=0.1,
        wheel_encoder_sample_interval_seconds=0.1,
        wheel_encoder_poll_interval_ms=1.0,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["wheel_encoder_gpio_capture_requested"] is True
    assert Path(report["wheel_encoder_gpio_capture_jsonl"]).exists()
    assert report["wheel_encoder_gpio_capture_report"]["usable_record_count"] == 2
    assert report["wheel_odometry_input_summary"]["wheel_odometry_ready"] is True
    assert _gate(report, "wheel_odometry")["passed"] is True
    assert report["next_action_status"] == "run_live_proof_next"


def test_field_session_can_defer_gpio_wheel_encoder_to_live_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))

    def live_proof(**kwargs):
        assert kwargs["wheel_odometry_jsonl_paths"] == []
        assert kwargs["wheel_encoder_gpio_capture"] is True
        assert kwargs["wheel_encoder_left_gpio"] == 20
        assert kwargs["wheel_encoder_right_gpio"] == 21
        assert kwargs["wheel_meters_per_tick"] == 0.05
        wheel_jsonl = kwargs["output_dir"] / "field-run" / "wheel-encoder-gpio-capture.jsonl"
        wheel_jsonl.parent.mkdir(parents=True, exist_ok=True)
        wheel_jsonl.write_text(
            "\n".join(
                json.dumps(payload)
                for payload in (
                    {"timestamp_s": 10.0, "dry_run": False, "odometry": {"cumulative_distance_m": 0.0}},
                    {"timestamp_s": 11.0, "dry_run": False, "odometry": {"cumulative_distance_m": 1.0}},
                )
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "source": "ins_dr_live_field_proof",
            "completion_ready": True,
            "scout_ins_dr_navigation_status": "field_ready",
            "field_proof_status": "passed",
            "proof_manifest_status": "passed",
            "wheel_odometry_jsonl_paths": [str(wheel_jsonl)],
        }

    monkeypatch.setattr(ins_dr_field_session, "run_live_field_proof", live_proof)
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        heading_evidence_jsonl_paths=[imu_jsonl],
        live_wheel_encoder_gpio_capture=True,
        wheel_meters_per_tick=0.05,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["live_wheel_encoder_gpio_capture_requested"] is True
    assert report["live_report"]["completion_ready"] is True
    assert report["wheel_odometry_input_summary"]["wheel_odometry_ready"] is True
    assert _gate(report, "wheel_odometry")["passed"] is True
    assert _gate(report, "live_field_proof")["passed"] is True
    assert report["scout_ins_dr_navigation_completion_ready"] is True


def test_field_session_rejects_idle_gpio_wheel_encoder_for_dr_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    monkeypatch.setattr(
        ins_dr_field_session,
        "capture_wheel_encoder_records",
        lambda **kwargs: [
            {
                "timestamp_s": 10.0,
                "dry_run": False,
                "wheel": {"left_ticks": 0, "right_ticks": 0, "cumulative_distance_m": 0.0},
                "odometry": {"cumulative_distance_m": 0.0},
            },
            {
                "timestamp_s": 11.0,
                "dry_run": False,
                "wheel": {"left_ticks": 0, "right_ticks": 0, "cumulative_distance_m": 0.0},
                "odometry": {"cumulative_distance_m": 0.0},
            },
        ],
    )
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_encoder_gpio_capture=True,
        wheel_meters_per_tick=0.05,
        wheel_encoder_capture_duration_seconds=0.1,
        wheel_encoder_sample_interval_seconds=0.1,
        wheel_encoder_poll_interval_ms=1.0,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    summary = report["wheel_odometry_input_summary"]
    capture_report = report["wheel_encoder_gpio_capture_report"]
    assert capture_report["usable_record_count"] == 2
    assert capture_report["left_tick_delta"] == 0
    assert capture_report["right_tick_delta"] == 0
    assert capture_report["distance_delta_m"] == 0.0
    assert capture_report["line_activity_observed"] is False
    assert capture_report["wheel_movement_observed"] is False
    assert capture_report["live_positive_wheel_movement_ready"] is False
    assert capture_report["missing_reason"] == "no_positive_wheel_motion_observed"
    assert summary["wheel_odometry_ready"] is False
    assert summary["positive_cumulative_distance_delta_count"] == 0
    assert summary["positive_tick_delta_count"] == 0
    assert summary["missing_reason"] == "no_positive_wheel_motion_observed"
    assert _gate(report, "wheel_odometry")["passed"] is False


def test_field_session_auto_captures_raw_imu_heading_for_dr_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    monkeypatch.setattr(
        ins_dr_field_session,
        "read_serial_frames",
        lambda **kwargs: parse_raw_hex_frames(_wit_frame_hex(0x53, [0, 0, 16384, 0])),
    )
    imu_port = tmp_path / "ttyIMU0"
    imu_port.write_text("", encoding="utf-8")
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        imu_heading_capture_port=imu_port,
        imu_heading_baud=9600,
        imu_heading_capture_duration_seconds=0.1,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["imu_heading_capture_requested"] is True
    assert Path(report["imu_heading_capture_report_json"]).exists()
    assert report["raw_imu_heading_evidence_summary"]["raw_imu_heading_ready"] is True
    assert report["raw_imu_heading_evidence_summary"]["raw_imu_heading_count"] == 1
    assert report["ins_dr_live_inputs_ready"] is True
    assert report["ins_dr_completion_failed_gate_names"] == ["live_field_proof"]
    assert _gate(report, "raw_imu_heading")["passed"] is True
    assert _gate(report, "wheel_odometry")["passed"] is True
    assert _gate(report, "live_field_proof")["status"] == "not_run"
    assert report["next_action_status"] == "run_live_proof_next"


def test_field_session_auto_imu_capture_keeps_gps_only_serial_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    monkeypatch.setattr(ins_dr_field_session, "read_serial_frames", lambda **kwargs: [])
    imu_port = tmp_path / "ttyIMU0"
    imu_port.write_text("", encoding="utf-8")
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        imu_heading_capture_port=imu_port,
        imu_heading_baud=9600,
        imu_heading_capture_duration_seconds=0.1,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["field_session_status"] == "dr_inputs_not_ready"
    assert report["imu_heading_capture_report"]["target_count"] == 1
    assert report["raw_imu_heading_evidence_summary"]["raw_imu_heading_ready"] is False
    assert report["raw_imu_heading_evidence_summary"]["missing_reason"] == "heading_evidence_jsonl_empty"
    assert report["wheel_odometry_input_summary"]["wheel_odometry_ready"] is True
    assert report["wheel_odometry_template_jsonl"] is None
    assert report["next_action_status"] == "collect_dr_evidence_inputs"
    assert report["live_report"] is None


def test_field_session_auto_imu_capture_does_not_count_unknown_wit_frames_as_raw_imu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    monkeypatch.setattr(
        ins_dr_field_session,
        "read_serial_frames",
        lambda **kwargs: parse_raw_hex_frames(_wit_frame_hex(0x40, [0, 0, 0, 0])),
    )
    imu_port = tmp_path / "ttyUSB0"
    imu_port.write_text("", encoding="utf-8")
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        imu_heading_capture_port=imu_port,
        imu_heading_baud=9600,
        imu_heading_capture_duration_seconds=0.1,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    summary = report["raw_imu_heading_evidence_summary"]
    assert summary["payload_count"] == 1
    assert summary["raw_imu_payload_count"] == 0
    assert summary["raw_imu_heading_count"] == 0
    assert summary["missing_reason"] == "no_raw_imu_heading_payload"
    assert _gate(report, "raw_imu_heading")["passed"] is False


def test_field_session_accepts_grove_9dof_magnetometer_as_heading_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    imu_jsonl = _write_grove_9dof_jsonl(tmp_path / "grove-9dof.jsonl")
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    summary = report["raw_imu_heading_evidence_summary"]
    assert summary["raw_imu_heading_ready"] is True
    assert summary["raw_imu_payload_count"] == 1
    assert summary["raw_imu_heading_count"] == 1
    assert round(summary["heading_deg_sample"][0], 2) == 45.0
    assert _gate(report, "raw_imu_heading")["passed"] is True
    assert report["next_action_status"] == "run_live_proof_next"


def test_field_session_can_capture_grove_9dof_heading_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    monkeypatch.setattr(
        ins_dr_field_session,
        "read_live_grove_imu_payload",
        lambda **kwargs: {
            "source": "pi_grove_imu_9dof_smoke",
            "hardware_kind": "grove_imu_9dof_icm20600_ak09918",
            "raw_imu_present": True,
            "raw_magnetometer_present": True,
            "read_status": "ok",
            "samples": [{"sequence": 0, "mag_status": "ok", "mag_raw": [0, 10, 0]}],
            "hardware_control_scope": "diagnostic_capture_only",
        },
    )
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        grove_imu_heading_capture=True,
        grove_imu_sample_count=1,
        grove_imu_sample_interval_ms=0,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["grove_imu_heading_capture_requested"] is True
    assert Path(report["grove_imu_heading_capture_jsonl"]).exists()
    assert report["raw_imu_heading_evidence_summary"]["raw_imu_heading_ready"] is True
    assert report["raw_imu_heading_evidence_summary"]["heading_deg_sample"] == [90.0]
    assert _gate(report, "raw_imu_heading")["passed"] is True


def test_field_session_watch_feeds_valid_fix_path_into_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    selected_port = tmp_path / "dev" / "serial" / "by-id" / "usb-good-gps"
    selected_port.parent.mkdir(parents=True)
    selected_port.write_text("", encoding="utf-8")
    watch_payloads = tmp_path / "watch" / "gnss-fix-watch-payloads.jsonl"
    watch_report_json = tmp_path / "watch" / "gnss-fix-watch-report.json"
    calls: list[dict] = []

    def watch(**kwargs):
        calls.append({"watch": kwargs})
        return {
            "source": "ins_dr_gnss_fix_watch",
            "watch_status": "valid_fix_observed",
            "watch_goal_satisfied": True,
            "ready_for_live_field_proof": True,
            "selected_gnss_port": str(selected_port),
            "payloads_jsonl": str(watch_payloads),
            "report_json": str(watch_report_json),
        }

    def readiness(**kwargs):
        calls.append({"readiness": kwargs})
        assert kwargs["gnss_port"] == selected_port
        assert kwargs["gnss_evidence_jsonl_paths"] == [watch_payloads]
        return _readiness(True)

    monkeypatch.setattr(ins_dr_field_session, "run_gnss_fix_watch", watch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", readiness)

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        gnss_watch_before_readiness=True,
        gnss_watch_window_seconds=0.1,
        gnss_watch_max_window_count=1,
        gnss_watch_poll_interval_seconds=0.0,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert [list(call)[0] for call in calls] == ["watch", "readiness"]
    assert report["field_session_status"] == "ready_for_live_proof"
    assert report["gnss_watch_status"] == "valid_fix_observed"
    assert report["gnss_watch_report_json"] == str(watch_report_json)
    assert report["readiness_input_gnss_port"] == str(selected_port)
    assert report["readiness_input_gnss_evidence_jsonl_paths"] == [str(watch_payloads)]


def test_field_session_watch_not_ready_keeps_live_proof_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    watch_payloads = tmp_path / "watch" / "gnss-fix-watch-payloads.jsonl"

    def watch(**kwargs):
        return {
            "source": "ins_dr_gnss_fix_watch",
            "watch_status": "timed_out_no_rf_signal",
            "watch_goal_satisfied": False,
            "ready_for_live_field_proof": False,
            "selected_gnss_port": None,
            "payloads_jsonl": str(watch_payloads),
            "report_json": str(tmp_path / "watch" / "gnss-fix-watch-report.json"),
        }

    def readiness(**kwargs):
        assert kwargs["gnss_port"] == Path("auto")
        assert kwargs["gnss_evidence_jsonl_paths"] == [watch_payloads]
        return _readiness(False)

    def fail_live_proof(**kwargs):
        raise AssertionError("live proof must not run when GNSS watch is not ready")

    monkeypatch.setattr(ins_dr_field_session, "run_gnss_fix_watch", watch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", readiness)
    monkeypatch.setattr(ins_dr_field_session, "run_live_field_proof", fail_live_proof)

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        run_live_proof=True,
        gnss_watch_before_readiness=True,
        gnss_watch_window_seconds=0.1,
        gnss_watch_max_window_count=1,
        gnss_watch_poll_interval_seconds=0.0,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["field_session_status"] == "gnss_watch_not_ready"
    assert report["scout_ins_dr_navigation_status"] == "not_ready_gnss_physical_evidence"
    assert report["ins_dr_completion_failed_gate_names"] == [
        "gnss_anchor",
        "raw_imu_heading",
        "wheel_odometry",
        "live_field_proof",
    ]
    assert _gate(report, "gnss_anchor")["status"] == "no_rf_signal_or_cno"
    assert _gate(report, "gnss_anchor")["evidence"]["gnss_watch_status"] == "timed_out_no_rf_signal"
    assert _gate(report, "live_field_proof")["status"] == "waiting_for_required_inputs"
    assert report["ready_for_live_field_proof"] is False
    assert report["completion_ready"] is False
    assert report["gnss_watch_status"] == "timed_out_no_rf_signal"
    assert report["gnss_watch_ready_for_live_field_proof"] is False
    assert report["next_action_status"] == "collect_physical_measurements"
    assert Path(report["next_action_json"]).exists()
    assert Path(report["next_action_md"]).exists()
    assert Path(report["gnss_physical_measurements_template_json"]).exists()
    assert Path(report["gnss_physical_measurements_template_md"]).exists()
    assert report["next_action"]["gnss_physical_measurements_template_json"] == report[
        "gnss_physical_measurements_template_json"
    ]
    template_payload = json.loads(Path(report["gnss_physical_measurements_template_json"]).read_text())
    assert "vcc_voltage_v" in template_payload["template"]
    assert "Physical Measurement Template" in Path(report["next_action_md"]).read_text()
    assert Path(report["wheel_odometry_template_jsonl"]).exists()
    assert Path(report["wheel_odometry_template_md"]).exists()
    assert report["next_action"]["wheel_odometry_template_jsonl"] == report["wheel_odometry_template_jsonl"]
    assert "Completion Gates" in Path(report["next_action_md"]).read_text()


def test_field_session_prefers_rf_signal_diagnosis_over_short_no_rf_watch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    watch_payloads = tmp_path / "watch" / "gnss-fix-watch-payloads.jsonl"

    monkeypatch.setattr(
        ins_dr_field_session,
        "run_gnss_fix_watch",
        lambda **kwargs: {
            "source": "ins_dr_gnss_fix_watch",
            "watch_status": "timed_out_no_rf_signal",
            "watch_goal_satisfied": False,
            "ready_for_live_field_proof": False,
            "selected_gnss_port": None,
            "max_cno_dbhz": 30,
            "gps_max_cno_dbhz": None,
            "intermittent_rf_observed": True,
            "valid_fix_window_count": 0,
            "gps_cno_window_count": 0,
            "any_cno_window_count": 1,
            "no_rf_window_count": 2,
            "window_stability": {
                "talker_signal_summary": {
                    "GL": {
                        "window_count": 1,
                        "nonzero_cno_window_count": 1,
                        "max_cno_dbhz": 30,
                        "rf_signal_observed": True,
                    }
                },
                "best_talker": "GL",
                "best_talker_cno_dbhz": 30,
            },
            "payloads_jsonl": str(watch_payloads),
            "report_json": str(tmp_path / "watch" / "gnss-fix-watch-report.json"),
        },
    )

    def readiness(**kwargs):
        report = _readiness(False)
        report["gnss_readiness_diagnosis"] = {
            "state": "non_gps_rf_signal_without_valid_fix",
            "next_operator_action": "Continue watch until GPS C/N0 or valid_fix_observed.",
        }
        report["gnss_evidence_summary"] = {
            "signal": {
                "talker_signal_summary": {
                    "GL": {
                        "nonzero_cno_count": 2,
                        "max_cno_dbhz": 30,
                        "rf_signal_observed": True,
                    }
                },
                "best_talker": "GL",
                "best_talker_cno_dbhz": 30,
            }
        }
        return report

    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", readiness)

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        gnss_watch_before_readiness=True,
        gnss_watch_window_seconds=0.1,
        gnss_watch_max_window_count=1,
        gnss_watch_poll_interval_seconds=0.0,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["next_action_status"] == "wait_for_valid_fix"
    assert report["gnss_watch_best_talker"] == "GL"
    assert report["gnss_watch_best_talker_cno_dbhz"] == 30
    assert report["next_action"]["gnss_watch_talker_signal_summary"]["GL"]["max_cno_dbhz"] == 30
    assert report["readiness_gnss_best_talker"] == "GL"
    assert report["readiness_gnss_best_talker_cno_dbhz"] == 30
    assert report["next_action"]["readiness_gnss_talker_signal_summary"]["GL"]["nonzero_cno_count"] == 2
    assert "Readiness best talker" in Path(report["next_action_md"]).read_text(encoding="utf-8")
    gate = _gate(report, "gnss_anchor")
    assert gate["status"] == "rf_signal_without_valid_fix"
    assert gate["blockers"] == ["GNSS RF/C/N0 exists, but valid fix is missing."]
    assert gate["evidence"]["gnss_watch_intermittent_rf_observed"] is True
    assert gate["evidence"]["gnss_watch_any_cno_window_count"] == 1
    assert gate["evidence"]["gnss_watch_no_rf_window_count"] == 2


def test_field_session_includes_physical_measurements_in_diagnosis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    measurements_json = tmp_path / "physical-measurements.json"
    measurements_json.write_text(
        json.dumps(
            {
                "module_label": "scout",
                "vcc_voltage_v": 3.3,
                "power_off_rf_center_to_gnd_ohm": 2.0,
                "power_off_antenna_center_to_gnd_ohm": 1000,
                "power_off_antenna_center_to_rf_in_ohm": 1.0,
                "power_off_antenna_shield_to_gnd_ohm": 0.2,
                "has_external_active_antenna": False,
                "antenna_patch_faces_sky": True,
                "antenna_clear_of_pi_ssd_battery_display_metal": True,
            }
        ),
        encoding="utf-8",
    )

    def diagnosis(**kwargs):
        physical = kwargs["physical"]
        assert physical["overall_status"] == "physical_fault_indicated"
        assert any("shorted to GND" in cause for cause in physical["likely_causes"])
        return {
            "source": "pi_gnss_diagnosis_report",
            "conclusion": {"status": "physical_fault_indicated"},
            "physical_check": {"status": "fail"},
        }

    monkeypatch.setattr(ins_dr_field_session, "build_diagnosis", diagnosis)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(False))

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        gnss_physical_measurements_json_path=measurements_json,
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["gnss_physical_measurements_json"] == str(measurements_json)
    assert report["gnss_physical_overall_status"] == "physical_fault_indicated"
    assert Path(report["gnss_physical_checklist_report_json"]).exists()
    assert report["diagnosis"]["conclusion"]["status"] == "physical_fault_indicated"
    assert report["next_action_status"] == "repair_physical_fault"
    assert report["scout_ins_dr_navigation_status"] == "not_ready_gnss_physical_fault"
    assert _gate(report, "gnss_anchor")["status"] == "physical_fault_indicated"
    assert "RF_IN to GND short check" in report["next_action"]["actions"][0]["evidence_required"]


def test_field_session_next_action_prompts_live_proof_when_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    monkeypatch.setattr(ins_dr_field_session, "build_field_readiness_report", lambda **kwargs: _readiness(True))
    imu_jsonl = _write_raw_imu_heading_jsonl(tmp_path / "imu-heading.jsonl")
    wheel_jsonl = _write_wheel_odometry_jsonl(tmp_path / "wheel.jsonl")

    report = run_field_session(
        output_dir=tmp_path / "session",
        mission_graph_path=tmp_path / "mission.json",
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        snapshot_ab_duration_seconds=0.1,
        snapshot_probe_duration_seconds=0.1,
        readiness_capture_duration_seconds=0.1,
        readiness_auto_select_duration_seconds=0.1,
    )

    assert report["field_session_status"] == "ready_for_live_proof"
    assert report["ins_dr_live_inputs_ready"] is True
    assert report["ins_dr_completion_failed_gate_names"] == ["live_field_proof"]
    assert report["next_action_status"] == "run_live_proof_next"
    assert report["next_action"]["actions"][0]["action"].startswith("Run live field proof")


def test_field_session_rejects_existing_artifacts_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapshot_and_diagnosis(monkeypatch)
    (tmp_path / "field-session-report.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="field session artifacts"):
        run_field_session(
            output_dir=tmp_path,
            mission_graph_path=tmp_path / "mission.json",
            snapshot_ab_duration_seconds=0.1,
            snapshot_probe_duration_seconds=0.1,
            readiness_capture_duration_seconds=0.1,
            readiness_auto_select_duration_seconds=0.1,
        )


def test_field_session_cli_success_requires_live_completion_when_requested() -> None:
    assert (
        ins_dr_field_session._cli_success(
            {"field_session_status": "live_proof_failed", "ready_for_live_field_proof": True},
            run_live_proof=True,
        )
        is False
    )
    assert (
        ins_dr_field_session._cli_success(
            {"field_session_status": "ready_for_live_proof", "ready_for_live_field_proof": True},
            run_live_proof=False,
        )
        is True
    )


def _stub_snapshot_and_diagnosis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ins_dr_field_session,
        "build_auto_gnss_targets",
        lambda **kwargs: (
            [],
            [
                {
                    "path": "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
                    "kind": "stable_by_id",
                    "priority": 0,
                }
            ],
        ),
    )
    monkeypatch.setattr(
        ins_dr_field_session,
        "collect_snapshot",
        lambda **kwargs: {
            "source": "pi_gnss_hardware_snapshot",
            "hardware_kind": "gnss_antenna_rf_hardware_snapshot",
            "verdict": {"per_target": {}, "next_required_evidence": []},
        },
    )
    monkeypatch.setattr(
        ins_dr_field_session,
        "build_diagnosis",
        lambda **kwargs: {
            "source": "pi_gnss_diagnosis_report",
            "conclusion": {"status": "not_yet_conclusive_gps_l1_environment_missing"},
        },
    )
    monkeypatch.setattr(ins_dr_field_session, "render_markdown", lambda report: "# Scout GNSS Hardware Diagnosis\n")


def _snapshot_with_command_response() -> dict:
    label = "auto_0_stable_by_id_usb_1a86_USB_Serial_if00_port0_115200"
    return {
        "source": "pi_gnss_hardware_snapshot",
        "hardware_kind": "gnss_antenna_rf_hardware_snapshot",
        "verdict": {
            "per_target": {
                label: {
                    "nmea_rx_path": "valid_nmea_received",
                    "command_path": "receiver_response_observed",
                    "fix_observed": False,
                    "gps_rf_signal_observed": False,
                    "any_rf_signal_observed": False,
                    "max_cno_dbhz": None,
                    "gps_max_cno_dbhz": None,
                    "antenna_text_status": "OK",
                    "antenna_supervisor_status": None,
                    "ubx_mon_hw_seen": False,
                    "ubx_nav_svinfo_seen": False,
                    "likely_state": "no_rf_signal_observed",
                }
            },
            "next_required_evidence": ["Measure target GNSS VCC to GND under load while NMEA is streaming"],
        },
        "ublox_probes": {
            label: {
                "ubx_frame_count": 7,
                "summary": {
                    "command_path_state": "receiver_response_observed",
                    "antenna_text_status": "OK",
                    "ubx_ack_nak_count": 7,
                    "ubx_ack_ack_count": 0,
                    "ubx_mon_hw_seen": False,
                    "ubx_nav_svinfo_seen": False,
                    "likely_state": "no_rf_signal_observed",
                    "max_cno_dbhz": None,
                },
            }
        },
    }


def _readiness(ready: bool) -> dict:
    return {
        "source": "ins_dr_field_readiness_check",
        "artifact_kind": "ins_dr_field_readiness_report",
        "field_run_readiness_status": "ready" if ready else "not_ready",
        "ready": ready,
        "ready_for_live_field_proof": ready,
        "selected_gnss_port": "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0" if ready else None,
        "gnss_auto_selection_summary": {
            "selection_status": "selected_valid_fix_candidate" if ready else "no_valid_fix_candidate",
        },
        "gnss_evidence_summary": {
            "signal": {
                "talker_signal_summary": {},
                "best_talker": None,
                "best_talker_cno_dbhz": None,
            }
        },
        "checks": [],
    }


def _write_raw_imu_heading_jsonl(path: Path, *, heading: float = 87.5) -> Path:
    path.write_text(
        json.dumps(
            {
                "source": "pi_hiwonder_imu_usb_smoke",
                "frame_type": "angle",
                "checksum_valid": True,
                "parsed": {"angle_deg": [0.0, 0.0, heading], "checksum_valid": True},
                "raw_imu_present": True,
                "hardware_control_scope": "diagnostic_capture_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_wheel_odometry_jsonl(path: Path) -> Path:
    path.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {"timestamp_s": 10.0, "odometry": {"cumulative_distance_m": 20.0}},
                {"timestamp_s": 11.0, "odometry": {"cumulative_distance_m": 23.0}},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_grove_9dof_jsonl(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "source": "pi_grove_imu_9dof_smoke",
                "hardware_kind": "grove_imu_9dof_icm20600_ak09918",
                "raw_imu_present": True,
                "raw_magnetometer_present": True,
                "read_status": "ok",
                "samples": [
                    {
                        "sequence": 0,
                        "accel_g": [0.0, 0.0, 1.0],
                        "gyro_dps": [0.0, 0.0, 0.0],
                        "mag_raw": [100, 100, -20],
                        "mag_status": "ok",
                    }
                ],
                "hardware_control_scope": "diagnostic_capture_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _gate(report: dict, name: str) -> dict:
    return next(gate for gate in report["ins_dr_completion_gate_summary"]["gates"] if gate["name"] == name)


def _wit_frame_hex(frame_type: int, values: list[int]) -> str:
    payload = b"".join(value.to_bytes(2, "little", signed=True) for value in values)
    frame = bytes([0x55, frame_type]) + payload
    return (frame + bytes([sum(frame) & 0xFF])).hex()
