import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tools import ins_dr_live_field_proof
from tools.ins_dr_live_field_proof import run_live_field_proof
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_live_field_proof.py"


def test_live_field_proof_raw_nmea_rehearsal_builds_route_but_not_completion(tmp_path: Path) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=87.5, distance_m=3.0)

    report = run_live_field_proof(
        output_dir=tmp_path,
        mission_id="ins_dr_live_rehearsal",
        gnss_port="auto",
        gnss_baud=9600,
        anchor_duration_seconds=0.1,
        reanchor_duration_seconds=0.1,
        distance_deltas_m=[3.0],
        heading_degs=[87.5],
        timestamp_s_values=[11.0],
        movement_window_seconds=0.0,
        raw_anchor_nmea=_gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
        raw_reanchor_nmea=_gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
        pretty=True,
    )

    assert report["source"] == "ins_dr_live_field_proof"
    assert report["hardware_control_scope"] == "diagnostic_live_field_proof_only"
    assert report["completion_ready"] is False
    assert report["scout_ins_dr_navigation_status"] == "not_field_ready"
    assert report["anchor_payload_count"] == 1
    assert report["dr_delta_count"] == 1
    assert report["reanchor_payload_count"] == 1
    assert report["movement_window_seconds"] == 0.0
    assert report["serial_resolution"]["auto_detection_status"] == "raw_nmea_rehearsal_no_serial_required"
    assert Path(report["route_gpx"]).exists()
    assert Path(report["mission_graph_json"]).exists()
    assert Path(report["map_context_geojson"]).exists()
    assert Path(report["route_scaffold_report_json"]).exists()
    assert Path(report["live_field_proof_report_json"]).exists()
    assert Path(report["operator_events_jsonl"]).exists()
    assert Path(report["proof_manifest_json"]).exists()
    assert Path(report["verification_report_json"]).exists()
    assert report["operator_event_count"] == len(report["operator_events"])
    assert [event["event_type"] for event in report["operator_events"]] == [
        "anchor_capture_start",
        "anchor_capture_complete",
        "route_scaffold_created",
        "dr_delta_recorded",
        "movement_window_skipped",
        "reanchor_capture_start",
        "reanchor_capture_complete",
        "completion_gate_complete",
    ]
    assert all(
        event["hardware_control_scope"] == "diagnostic_live_field_proof_operator_guidance_only"
        for event in report["operator_events"]
    )

    field_report = json.loads(Path(report["field_report_json"]).read_text(encoding="utf-8"))
    persisted_report = json.loads(Path(report["live_field_proof_report_json"]).read_text(encoding="utf-8"))
    operator_events = [
        json.loads(line) for line in Path(report["operator_events_jsonl"]).read_text(encoding="utf-8").splitlines()
    ]
    assert field_report["field_proof_status"] == "failed"
    assert field_report["replayed_gnss_failure_count"] == 2
    assert field_report["route_corridor_failure_count"] == 0
    assert persisted_report["source"] == "ins_dr_live_field_proof"
    assert operator_events[-1]["event_type"] == "completion_gate_complete"


def test_live_field_proof_cli_raw_nmea_rehearsal_returns_not_ready(tmp_path: Path) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=87.5, distance_m=3.0)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--mission-id",
            "ins_dr_live_cli_rehearsal",
            "--gnss-port",
            "auto",
            "--raw-anchor-nmea",
            _gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            "87.5",
            "--timestamp-s",
            "11.0",
            "--raw-reanchor-nmea",
            _gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "[ins-dr-live] Capturing GNSS anchor" in result.stderr
    assert "[ins-dr-live] Completion gate finished with status not_field_ready." in result.stderr
    report = json.loads(result.stdout)
    assert report["completion_ready"] is False
    assert report["field_proof_status"] == "failed"
    assert Path(report["live_field_proof_report_json"]).exists()
    assert Path(report["operator_events_jsonl"]).exists()


def test_live_field_proof_persists_anchor_failure_gnss_evidence(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--mission-id",
            "ins_dr_live_no_anchor",
            "--gnss-port",
            "auto",
            "--raw-anchor-nmea",
            "\n".join(
                [
                    "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
                    "$GPGSV,1,1,00,0*65",
                ]
            ),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            "87.5",
            "--raw-reanchor-nmea",
            _gga_sentence(lat=25.06370833, lon=121.654115, time_value="000012.000"),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "GNSS anchor capture did not produce a valid position" in result.stderr
    report = json.loads(result.stdout)
    assert report["failure_stage"] == "anchor_capture"
    assert report["completion_ready"] is False
    assert report["proof_manifest_status"] == "not_created"
    assert report["anchor_payload_count"] == 2
    assert report["anchor_gnss_signal_summary"]["gsv_sentence_count"] == 1
    assert report["anchor_gnss_signal_summary"]["reported_visible_satellites"] == 0
    assert report["anchor_gnss_signal_summary"]["nonzero_cno_count"] == 0
    assert report["anchor_failure_diagnosis"]["state"] == "no_rf_signal_observed"
    assert report["anchor_failure_diagnosis"]["any_rf_signal_observed"] is False
    assert Path(report["anchor_jsonl"]).exists()
    assert Path(report["live_field_proof_report_json"]).exists()
    assert Path(report["operator_events_jsonl"]).exists()
    assert not Path(report["proof_manifest_json"]).exists()
    persisted_report = json.loads(Path(report["live_field_proof_report_json"]).read_text(encoding="utf-8"))
    operator_events = [
        json.loads(line) for line in Path(report["operator_events_jsonl"]).read_text(encoding="utf-8").splitlines()
    ]
    assert persisted_report["failure_stage"] == "anchor_capture"
    assert [event["event_type"] for event in operator_events] == [
        "anchor_capture_start",
        "anchor_capture_failed",
    ]
    assert operator_events[-1]["details"]["anchor_failure_diagnosis"]["state"] == "no_rf_signal_observed"


def test_live_field_proof_anchor_failure_distinguishes_rf_signal_without_fix(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--mission-id",
            "ins_dr_live_rf_no_fix",
            "--gnss-port",
            "auto",
            "--raw-anchor-nmea",
            "\n".join(
                [
                    "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
                    "$GLGSV,1,1,01,70,,,30,0*7C",
                ]
            ),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            "87.5",
            "--raw-reanchor-nmea",
            _gga_sentence(lat=25.06370833, lon=121.654115, time_value="000012.000"),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["failure_stage"] == "anchor_capture"
    assert report["anchor_gnss_signal_summary"]["max_cno_dbhz"] == 30
    assert report["anchor_failure_diagnosis"]["state"] == "rf_signal_without_valid_fix"
    assert report["anchor_failure_diagnosis"]["any_rf_signal_observed"] is True
    assert report["anchor_failure_diagnosis"]["gps_rf_signal_observed"] is False
    assert report["anchor_failure_diagnosis"]["max_cno_dbhz"] == 30


def test_live_field_proof_waits_for_valid_anchor_fix_before_dr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    heading = 87.5
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=heading, distance_m=3.0)
    wheel_jsonl = tmp_path / "wheel-raw.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {
                    "timestamp_s": 10.5,
                    "raw_evidence_ref": "wheel-raw.jsonl:1",
                    "odometry": {"cumulative_distance_m": 20.0, "heading_deg": heading},
                },
                {
                    "timestamp_s": 11.0,
                    "raw_evidence_ref": "wheel-raw.jsonl:2",
                    "odometry": {"cumulative_distance_m": 23.0, "heading_deg": heading},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    anchor_attempts = [
        "\n".join(
            [
                "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
                "$GLGSV,1,1,01,70,,,30,0*7C",
            ]
        ),
        _gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
    ]

    def serial_capture(
        *,
        raw_nmea: str | None,
        port: str,
        baud: int,
        duration_seconds: float,
    ) -> list[dict]:
        if raw_nmea is None:
            raw_nmea = anchor_attempts.pop(0)
        return parse_raw_nmea(
            raw_nmea,
            device_port=port,
            baud=baud,
            capture_mode="serial_device",
        )

    monkeypatch.setattr(ins_dr_live_field_proof, "_capture_gnss_payloads", serial_capture)

    report = run_live_field_proof(
        output_dir=tmp_path / "proof",
        mission_id="ins_dr_live_wait_for_anchor",
        gnss_port="/dev/ttyUSB0",
        gnss_baud=115200,
        anchor_duration_seconds=0.1,
        anchor_wait_timeout_seconds=10.0,
        anchor_retry_interval_seconds=0.0,
        reanchor_duration_seconds=0.1,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        raw_reanchor_nmea=_gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
        pretty=True,
    )

    assert report["completion_ready"] is True
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["anchor_capture_summary"]["mode"] == "wait_until_valid_fix"
    assert report["anchor_capture_summary"]["attempt_count"] == 2
    assert report["anchor_capture_summary"]["valid_fix_observed"] is True
    assert report["anchor_capture_summary"]["payload_count"] == 3
    assert [event["event_type"] for event in report["operator_events"][:4]] == [
        "anchor_capture_start",
        "anchor_capture_attempt",
        "anchor_capture_attempt",
        "anchor_capture_complete",
    ]


def test_live_field_proof_waits_for_valid_reanchor_fix_before_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    heading = 87.5
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=heading, distance_m=3.0)
    wheel_jsonl = tmp_path / "wheel-raw.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {
                    "timestamp_s": 10.5,
                    "raw_evidence_ref": "wheel-raw.jsonl:1",
                    "odometry": {"cumulative_distance_m": 20.0, "heading_deg": heading},
                },
                {
                    "timestamp_s": 11.0,
                    "raw_evidence_ref": "wheel-raw.jsonl:2",
                    "odometry": {"cumulative_distance_m": 23.0, "heading_deg": heading},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    reanchor_attempts = [
        "\n".join(
            [
                "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
                "$GLGSV,1,1,01,70,,,30,0*7C",
            ]
        ),
        _gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
    ]

    def serial_capture(
        *,
        raw_nmea: str | None,
        port: str,
        baud: int,
        duration_seconds: float,
    ) -> list[dict]:
        if raw_nmea is None:
            raw_nmea = reanchor_attempts.pop(0)
        return parse_raw_nmea(
            raw_nmea,
            device_port=port,
            baud=baud,
            capture_mode="serial_device",
        )

    monkeypatch.setattr(ins_dr_live_field_proof, "_capture_gnss_payloads", serial_capture)

    report = run_live_field_proof(
        output_dir=tmp_path / "proof",
        mission_id="ins_dr_live_wait_for_reanchor",
        gnss_port="/dev/ttyUSB0",
        gnss_baud=115200,
        anchor_duration_seconds=0.1,
        reanchor_duration_seconds=0.1,
        reanchor_wait_timeout_seconds=10.0,
        reanchor_retry_interval_seconds=0.0,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        raw_anchor_nmea=_gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
        pretty=True,
    )

    assert report["completion_ready"] is True
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["reanchor_capture_summary"]["mode"] == "wait_until_valid_fix"
    assert report["reanchor_capture_summary"]["attempt_count"] == 2
    assert report["reanchor_capture_summary"]["valid_fix_observed"] is True
    assert report["reanchor_capture_summary"]["payload_count"] == 3
    assert "reanchor_capture_attempt" in [event["event_type"] for event in report["operator_events"]]
    reanchor_complete = [
        event for event in report["operator_events"] if event["event_type"] == "reanchor_capture_complete"
    ][0]
    assert reanchor_complete["details"]["reanchor_capture_summary"]["valid_fix_observed"] is True


def test_live_field_proof_can_use_provider_wheel_jsonl_when_gnss_capture_is_serial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    heading = 87.5
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=heading, distance_m=3.0)
    wheel_jsonl = tmp_path / "wheel-raw.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {
                    "timestamp_s": 10.5,
                    "raw_evidence_ref": "wheel-raw.jsonl:1",
                    "odometry": {"cumulative_distance_m": 20.0, "heading_deg": heading},
                },
                {
                    "timestamp_s": 11.0,
                    "raw_evidence_ref": "wheel-raw.jsonl:2",
                    "odometry": {"cumulative_distance_m": 23.0, "heading_deg": heading},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    def serial_capture(
        *,
        raw_nmea: str | None,
        port: str,
        baud: int,
        duration_seconds: float,
    ) -> list[dict]:
        assert raw_nmea is not None
        return parse_raw_nmea(
            raw_nmea,
            device_port=port,
            baud=baud,
            capture_mode="serial_device",
        )

    monkeypatch.setattr(ins_dr_live_field_proof, "_capture_gnss_payloads", serial_capture)

    report = run_live_field_proof(
        output_dir=tmp_path / "proof",
        mission_id="ins_dr_live_wheel_provider",
        gnss_port="/dev/ttyUSB0",
        gnss_baud=115200,
        anchor_duration_seconds=0.1,
        reanchor_duration_seconds=0.1,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        raw_anchor_nmea=_gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
        raw_reanchor_nmea=_gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
        pretty=True,
    )

    assert report["completion_ready"] is True
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["dr_evidence_mode"] == "wheel_odometry_jsonl"
    assert report["wheel_odometry_jsonl_paths"] == [str(wheel_jsonl)]
    assert report["wheel_odometry_record_count"] == 2
    manifest = json.loads(Path(report["proof_manifest_json"]).read_text(encoding="utf-8"))
    assert str(wheel_jsonl) in [ref["path"] for ref in manifest["input_refs"]]
    field_report = json.loads(Path(report["field_report_json"]).read_text(encoding="utf-8"))
    assert field_report["dr_distance_source_failure_count"] == 0
    review = field_report["dr_distance_source_summary"]["reviews"][0]
    assert review["kind"] == "wheel_or_encoder_odometry"
    assert review["provenance"]["evidence_scope"] == "wheel_encoder_provider_delta"


def test_live_field_proof_captures_gpio_wheel_encoder_after_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    heading = 87.5
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=heading, distance_m=3.0)

    def capture_wheel(**kwargs):
        assert kwargs["left_gpio"] == 20
        assert kwargs["right_gpio"] == 21
        assert kwargs["meters_per_tick"] == 0.5
        assert kwargs["duration_seconds"] == 0.1
        return [
            {
                "timestamp_s": 10.0,
                "dry_run": False,
                "wheel": {
                    "left_ticks": 0,
                    "right_ticks": 0,
                    "meters_per_tick": 0.5,
                    "cumulative_distance_m": 0.0,
                },
                "odometry": {"cumulative_distance_m": 0.0, "heading_deg": heading},
            },
            {
                "timestamp_s": 11.0,
                "dry_run": False,
                "wheel": {
                    "left_ticks": 6,
                    "right_ticks": 6,
                    "meters_per_tick": 0.5,
                    "cumulative_distance_m": 3.0,
                },
                "odometry": {"cumulative_distance_m": 3.0, "heading_deg": heading},
            },
        ]

    def serial_capture(
        *,
        raw_nmea: str | None,
        port: str,
        baud: int,
        duration_seconds: float,
    ) -> list[dict]:
        assert raw_nmea is not None
        return parse_raw_nmea(
            raw_nmea,
            device_port=port,
            baud=baud,
            capture_mode="serial_device",
        )

    monkeypatch.setattr(ins_dr_live_field_proof, "capture_wheel_encoder_records", capture_wheel)
    monkeypatch.setattr(ins_dr_live_field_proof, "_capture_gnss_payloads", serial_capture)

    report = run_live_field_proof(
        output_dir=tmp_path / "proof",
        mission_id="ins_dr_live_gpio_wheel",
        gnss_port="/dev/ttyUSB0",
        gnss_baud=115200,
        anchor_duration_seconds=0.1,
        reanchor_duration_seconds=0.1,
        raw_anchor_nmea=_gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
        raw_reanchor_nmea=_gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
        wheel_encoder_gpio_capture=True,
        wheel_meters_per_tick=0.5,
        wheel_encoder_capture_duration_seconds=0.1,
        wheel_encoder_sample_interval_seconds=0.1,
        wheel_encoder_poll_interval_ms=1.0,
        pretty=True,
    )

    assert report["completion_ready"] is True
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["dr_evidence_mode"] == "wheel_odometry_jsonl"
    assert report["wheel_encoder_gpio_capture_requested"] is True
    assert report["wheel_encoder_gpio_capture_report"]["final_cumulative_distance_m"] == 3.0
    assert len(report["wheel_odometry_jsonl_paths"]) == 1
    assert report["wheel_odometry_jsonl_paths"][0].endswith("field-run/wheel-encoder-gpio-capture.jsonl")
    assert Path(report["wheel_odometry_jsonl_paths"][0]).exists()
    assert report["wheel_odometry_record_count"] == 2
    event_types = [event["event_type"] for event in report["operator_events"]]
    assert "wheel_encoder_gpio_capture_start" in event_types
    assert "wheel_encoder_gpio_capture_complete" in event_types
    assert "movement_window_consumed_by_wheel_encoder_capture" in event_types


def test_live_field_proof_uses_selected_gnss_port_from_ready_readiness_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    heading = 87.5
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=heading, distance_m=3.0)
    selected_port = tmp_path / "dev" / "serial" / "by-id" / "usb-good-gps"
    selected_port.parent.mkdir(parents=True)
    selected_port.write_text("", encoding="utf-8")
    readiness_json = tmp_path / "readiness.json"
    readiness_json.write_text(
        json.dumps(
            {
                "source": "ins_dr_field_readiness_check",
                "field_run_readiness_status": "ready",
                "ready": True,
                "ready_for_live_field_proof": True,
                "selected_gnss_port": str(selected_port),
                "gnss_auto_selection_summary": {
                    "selection_status": "selected_valid_fix_candidate",
                    "selected_gnss_port": str(selected_port),
                },
            }
        ),
        encoding="utf-8",
    )
    wheel_jsonl = tmp_path / "wheel-raw.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {
                    "timestamp_s": 10.5,
                    "raw_evidence_ref": "wheel-raw.jsonl:1",
                    "odometry": {"cumulative_distance_m": 20.0, "heading_deg": heading},
                },
                {
                    "timestamp_s": 11.0,
                    "raw_evidence_ref": "wheel-raw.jsonl:2",
                    "odometry": {"cumulative_distance_m": 23.0, "heading_deg": heading},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    serial_captures = [
        _gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
        _gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
    ]

    def serial_capture(
        *,
        raw_nmea: str | None,
        port: str,
        baud: int,
        duration_seconds: float,
    ) -> list[dict]:
        assert raw_nmea is None
        assert port == str(selected_port)
        return parse_raw_nmea(
            serial_captures.pop(0),
            device_port=port,
            baud=baud,
            capture_mode="serial_device",
        )

    monkeypatch.setattr(ins_dr_live_field_proof, "_capture_gnss_payloads", serial_capture)

    report = run_live_field_proof(
        output_dir=tmp_path / "proof",
        mission_id="ins_dr_live_readiness_selected",
        gnss_port="auto",
        gnss_baud=115200,
        anchor_duration_seconds=0.1,
        reanchor_duration_seconds=0.1,
        readiness_report_json_path=readiness_json,
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        pretty=True,
    )

    assert report["completion_ready"] is True
    assert report["gnss_port"] == str(selected_port)
    assert report["serial_resolution"]["auto_detection_status"] == "selected_from_readiness_report"
    assert report["serial_resolution"]["readiness_auto_selection_status"] == "selected_valid_fix_candidate"


def test_live_field_proof_rejects_not_ready_readiness_report(tmp_path: Path) -> None:
    selected_port = tmp_path / "dev" / "serial" / "by-id" / "usb-no-fix"
    selected_port.parent.mkdir(parents=True)
    selected_port.write_text("", encoding="utf-8")
    readiness_json = tmp_path / "readiness-not-ready.json"
    readiness_json.write_text(
        json.dumps(
            {
                "source": "ins_dr_field_readiness_check",
                "field_run_readiness_status": "not_ready",
                "ready": False,
                "ready_for_live_field_proof": False,
                "selected_gnss_port": str(selected_port),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="readiness report is not ready"):
        run_live_field_proof(
            output_dir=tmp_path / "proof",
            mission_id="ins_dr_live_readiness_not_ready",
            gnss_port="auto",
            gnss_baud=115200,
            anchor_duration_seconds=0.1,
            reanchor_duration_seconds=0.1,
            readiness_report_json_path=readiness_json,
            distance_deltas_m=[3.0],
            heading_degs=[87.5],
            timestamp_s_values=[11.0],
        )


def test_live_field_proof_can_use_raw_imu_heading_with_wheel_distance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_lat = 25.06370833
    start_lon = 121.654085
    heading = 87.5
    finish_lat, finish_lon = _destination_point(start_lat, start_lon, heading_deg=heading, distance_m=3.0)
    imu_jsonl = tmp_path / "imu-heading.jsonl"
    imu_jsonl.write_text(
        json.dumps(
            {
                "source": "pi_hiwonder_imu_usb_smoke",
                "timestamp_s": 10.5,
                "frame_type": "angle",
                "checksum_valid": True,
                "parsed": {"angle_deg": [0.0, 0.0, heading], "checksum_valid": True},
                "raw_bytes_hex": "55530000000000000000a8",
                "raw_imu_present": True,
                "hardware_control_scope": "diagnostic_capture_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    wheel_jsonl = tmp_path / "wheel-raw.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {
                    "timestamp_s": 10.6,
                    "raw_evidence_ref": "wheel-raw.jsonl:1",
                    "odometry": {"cumulative_distance_m": 20.0},
                },
                {
                    "timestamp_s": 11.0,
                    "raw_evidence_ref": "wheel-raw.jsonl:2",
                    "odometry": {"cumulative_distance_m": 23.0},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    def serial_capture(
        *,
        raw_nmea: str | None,
        port: str,
        baud: int,
        duration_seconds: float,
    ) -> list[dict]:
        assert raw_nmea is not None
        return parse_raw_nmea(
            raw_nmea,
            device_port=port,
            baud=baud,
            capture_mode="serial_device",
        )

    monkeypatch.setattr(ins_dr_live_field_proof, "_capture_gnss_payloads", serial_capture)

    report = run_live_field_proof(
        output_dir=tmp_path / "proof",
        mission_id="ins_dr_live_imu_heading_wheel",
        gnss_port="/dev/ttyUSB0",
        gnss_baud=115200,
        anchor_duration_seconds=0.1,
        reanchor_duration_seconds=0.1,
        heading_evidence_jsonl_paths=[imu_jsonl],
        wheel_odometry_jsonl_paths=[wheel_jsonl],
        raw_anchor_nmea=_gga_sentence(lat=start_lat, lon=start_lon, time_value="000010.000"),
        raw_reanchor_nmea=_gga_sentence(lat=finish_lat, lon=finish_lon, time_value="000012.000"),
        pretty=True,
    )

    assert report["completion_ready"] is True
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["heading_evidence_payload_count"] == 1
    assert report["heading_evidence_jsonl_paths"] == [str(imu_jsonl)]
    assert "heading_evidence_loaded" in [event["event_type"] for event in report["operator_events"]]
    manifest = json.loads(Path(report["proof_manifest_json"]).read_text(encoding="utf-8"))
    assert str(imu_jsonl) in [ref["path"] for ref in manifest["input_refs"]]
    assert str(wheel_jsonl) in [ref["path"] for ref in manifest["input_refs"]]
    field_report = json.loads(Path(report["field_report_json"]).read_text(encoding="utf-8"))
    assert field_report["dr_heading_failure_count"] == 0
    assert field_report["dr_heading_summary"]["reviews"][0]["heading_deg"] == heading


def test_live_field_proof_rejects_manual_and_wheel_inputs_together(tmp_path: Path) -> None:
    wheel_jsonl = tmp_path / "wheel-raw.jsonl"
    wheel_jsonl.write_text(
        json.dumps({"timestamp_s": 10.0, "odometry": {"cumulative_distance_m": 20.0}}) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path / "proof"),
            "--mission-id",
            "ins_dr_live_mixed_dr_inputs",
            "--raw-anchor-nmea",
            _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            "87.5",
            "--wheel-odometry-jsonl",
            str(wheel_jsonl),
            "--raw-reanchor-nmea",
            _gga_sentence(lat=25.06371, lon=121.654115, time_value="000012.000"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert (
        "provide exactly one of distance_deltas_m, wheel_odometry_jsonl_paths, or wheel_encoder_gpio_capture"
        in result.stderr
    )


def test_live_field_proof_requires_route_heading_when_dr_heading_is_missing(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--mission-id",
            "ins_dr_live_missing_heading",
            "--gnss-port",
            "auto",
            "--raw-anchor-nmea",
            _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--raw-reanchor-nmea",
            _gga_sentence(lat=25.06370833, lon=121.654115, time_value="000012.000"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "provide --route-heading-deg, --heading-evidence-jsonl, or at least one --heading-deg" in result.stderr


def test_live_field_proof_rejects_negative_movement_window(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--mission-id",
            "ins_dr_live_negative_window",
            "--raw-anchor-nmea",
            _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            "87.5",
            "--raw-reanchor-nmea",
            _gga_sentence(lat=25.06371, lon=121.654115, time_value="000012.000"),
            "--movement-window-seconds",
            "-1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "movement_window_seconds must be non-negative" in result.stderr


def _destination_point(lat: float, lon: float, *, heading_deg: float, distance_m: float) -> tuple[float, float]:
    earth_radius_m = 6_371_000.0
    angular_distance = distance_m / earth_radius_m
    bearing = math.radians(heading_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    normalized_lon = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return round(math.degrees(lat2), 8), round(normalized_lon, 8)


def _gga_sentence(*, lat: float, lon: float, time_value: str) -> str:
    lat_value, lat_hemi = _nmea_lat(lat)
    lon_value, lon_hemi = _nmea_lon(lon)
    body = f"GPGGA,{time_value},{lat_value},{lat_hemi},{lon_value},{lon_hemi},1,09,0.8,80.0,M,20.1,M,,"
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def _nmea_lat(value: float) -> tuple[str, str]:
    hemi = "N" if value >= 0 else "S"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:02d}{minutes:07.4f}", hemi


def _nmea_lon(value: float) -> tuple[str, str]:
    hemi = "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:03d}{minutes:07.4f}", hemi
