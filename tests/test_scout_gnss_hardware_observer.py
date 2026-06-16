from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scout_gnss_hardware_observer import (
    GnssHardwareObserver,
    GnssHardwareObserverConfig,
    boundary_fields,
    candidate_from_record,
    load_jsonl_tail,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scout_gnss_hardware_observer.py"


def test_observer_projects_sx1303_gateway_gps_summary_to_live_snapshot(tmp_path: Path) -> None:
    gateway_jsonl = tmp_path / "gateway.jsonl"
    grove_jsonl = tmp_path / "grove.jsonl"
    _write_jsonl(gateway_jsonl, [_gateway_record(captured_at="2026-06-16T01:00:00Z")])

    observer = GnssHardwareObserver(
        GnssHardwareObserverConfig(
            evidence_dir=tmp_path / "observer",
            gateway_jsonl=gateway_jsonl,
            grove_jsonl=grove_jsonl,
        )
    )

    status = observer.refresh()
    snapshot = json.loads(observer.snapshot_path.read_text(encoding="utf-8"))

    assert status["artifact_kind"] == "scout_gnss_hardware_observer_status"
    assert status["selected_source"] == "lorawan_gateway_gps"
    assert status["decision"] == "gnss_fix_available"
    assert status["valid_source_count"] == 1
    assert status["boundary"] == boundary_fields()
    assert status["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert status["boundary"]["safety_api_called"] is False
    assert status["boundary"]["lorawan_uplink_allowed"] is False

    assert snapshot["snapshot_status"] == "valid_fix"
    assert snapshot["source"] == "lorawan_gateway_gps"
    assert snapshot["lat"] == 25.123456
    assert snapshot["lon"] == 121.654321
    assert snapshot["hdop"] == 1.2
    assert snapshot["satellite_count"] == 9
    assert snapshot["max_cno_dbhz"] == 37.0
    assert snapshot["selected_port"] == "/dev/serial0"
    assert snapshot["selected_baud"] == 9600
    assert snapshot["runtime_safety_truth"] is False
    assert snapshot["safety_api_called"] is False


def test_observer_uses_grove_gps_module_when_gateway_has_no_valid_fix(tmp_path: Path) -> None:
    gateway_jsonl = tmp_path / "gateway.jsonl"
    grove_jsonl = tmp_path / "grove.jsonl"
    _write_jsonl(gateway_jsonl, [_gateway_no_stream_record()])
    _write_jsonl(grove_jsonl, [_grove_record(captured_at="2026-06-16T01:01:00Z")])
    observer = GnssHardwareObserver(
        GnssHardwareObserverConfig(
            evidence_dir=tmp_path / "observer",
            gateway_jsonl=gateway_jsonl,
            grove_jsonl=grove_jsonl,
        )
    )

    status = observer.refresh()

    assert status["active_listening_source_count"] == 2
    assert status["selected_source"] == "grove_gps_module"
    assert status["listening_sources"][0]["status"] == "records_without_fix_candidate"
    assert status["listening_sources"][1]["status"] == "fix_available"
    assert status["live_navigation_snapshot"]["source"] == "grove_gps_module"
    assert status["live_navigation_snapshot"]["selected_port"] == "/dev/ttyAMA0"
    assert status["live_navigation_snapshot"]["last_anchor_at"] == "2026-06-16T01:01:00Z"


def test_observer_writes_no_valid_fix_snapshot_without_fabricating_position(tmp_path: Path) -> None:
    gateway_jsonl = tmp_path / "gateway.jsonl"
    grove_jsonl = tmp_path / "grove.jsonl"
    gateway_jsonl.write_text("{not-json}\n" + json.dumps(_gateway_no_stream_record()) + "\n", encoding="utf-8")

    observer = GnssHardwareObserver(
        GnssHardwareObserverConfig(
            evidence_dir=tmp_path / "observer",
            gateway_jsonl=gateway_jsonl,
            grove_jsonl=grove_jsonl,
        )
    )

    status = observer.refresh()
    snapshot = json.loads(observer.snapshot_path.read_text(encoding="utf-8"))

    assert status["selected_source"] is None
    assert status["decision"] == "gnss_listening_without_valid_fix"
    assert status["listening_sources"][0]["invalid_json_line_count"] == 1
    assert snapshot["snapshot_status"] == "no_valid_fix"
    assert "lat" not in snapshot
    assert "lon" not in snapshot
    assert snapshot["boundary"]["runtime_safety_truth"] is False


def test_candidate_parser_prefers_gateway_latest_valid_fix_over_first_sentence() -> None:
    observer = GnssHardwareObserver(GnssHardwareObserverConfig())
    gateway_spec = observer.source_specs()[0]
    record = _gateway_record(captured_at="2026-06-16T01:00:00Z")
    record["best_candidate"]["first_nmea_payload"] = {
        "source": "pi_gnss_nmea_smoke",
        "sentence_type": "GPGSV",
        "position": {"lat": None, "lon": None, "altitude_m": None},
        "fix_quality": {"valid": False, "satellites": 12},
        "checksum_valid": True,
    }

    candidate = candidate_from_record(record, gateway_spec)

    assert candidate is not None
    assert candidate["position_valid"] is True
    assert candidate["fix_valid"] is True
    assert candidate["sentence_type"] == "GNGGA"


def test_load_jsonl_tail_counts_invalid_lines(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"idx": 1}),
                "{bad",
                json.dumps({"idx": 2}),
                json.dumps({"idx": 3}),
            ]
        ),
        encoding="utf-8",
    )

    records, invalid = load_jsonl_tail(path, max_records=3)

    assert records == [{"idx": 2}, {"idx": 3}]
    assert invalid == 1


def test_cli_once_writes_status_and_rejects_invalid_arguments(tmp_path: Path) -> None:
    gateway_jsonl = tmp_path / "gateway.jsonl"
    _write_jsonl(gateway_jsonl, [_gateway_record(captured_at="2026-06-16T01:00:00Z")])
    evidence_dir = tmp_path / "observer"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--once",
            "--evidence-dir",
            str(evidence_dir),
            "--gateway-jsonl",
            str(gateway_jsonl),
            "--grove-jsonl",
            str(tmp_path / "missing-grove.jsonl"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_status = json.loads(result.stdout)
    status = json.loads((evidence_dir / "gnss_hardware_observer_status.json").read_text(encoding="utf-8"))
    assert stdout_status["selected_source"] == "lorawan_gateway_gps"
    assert status["selected_source"] == "lorawan_gateway_gps"

    invalid = subprocess.run(
        [sys.executable, str(SCRIPT), "--once", "--max-records", "0"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "--max-records must be at least 1" in invalid.stderr


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _gateway_record(*, captured_at: str) -> dict:
    return {
        "captured_at": captured_at,
        "source": "pi_sx1303_gateway_gps_nmea_smoke",
        "hardware_kind": "sx1303_gateway_hat_l76k_gnss_uart",
        "status": "nmea_ok",
        "nmea_available": True,
        "selected_port": "/dev/serial0",
        "selected_baud": 9600,
        "best_candidate": {
            "port": "/dev/serial0",
            "baud": 9600,
            "status": "nmea_ok",
            "first_nmea_payload": _grove_record(captured_at=captured_at),
            "gnss_fix_summary": {
                "has_valid_fix": True,
                "valid_fix_count": 1,
                "latest_valid_fix": {
                    "sentence_type": "GNGGA",
                    "gnss_time_utc": "01:00:00.000Z",
                    "position": {
                        "lat": 25.123456,
                        "lon": 121.654321,
                        "altitude_m": 87.5,
                    },
                    "motion": {
                        "speed_mps": 0.0,
                        "course_deg": 180.0,
                    },
                    "quality": 1,
                    "status": None,
                    "satellites": 9,
                    "hdop": 1.2,
                },
            },
            "gnss_signal_summary": {
                "max_cno_dbhz": 37,
                "gps_max_cno_dbhz": 34,
            },
        },
        "packet_forwarder_started": False,
        "rf_tx_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
    }


def _gateway_no_stream_record() -> dict:
    return {
        "captured_at": "2026-06-16T01:00:00Z",
        "source": "pi_sx1303_gateway_gps_nmea_smoke",
        "hardware_kind": "sx1303_gateway_hat_l76k_gnss_uart",
        "status": "no_stream",
        "nmea_available": False,
        "best_candidate": None,
        "packet_forwarder_started": False,
        "rf_tx_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
    }


def _grove_record(*, captured_at: str) -> dict:
    return {
        "captured_at": captured_at,
        "source": "pi_gnss_nmea_smoke",
        "hardware_kind": "serial_gnss_nmea",
        "device_port": "/dev/ttyAMA0",
        "baud": 9600,
        "sentence_type": "GNGGA",
        "gnss_time_utc": "01:01:00.000Z",
        "position": {
            "lat": 24.987654,
            "lon": 121.123456,
            "altitude_m": 50.0,
        },
        "fix_quality": {
            "status": None,
            "valid": True,
            "quality": 1,
            "satellites": 8,
            "hdop": 1.4,
        },
        "motion": {
            "speed_mps": 0.1,
            "course_deg": 90.0,
        },
        "checksum_valid": True,
        "primary_truth_scope": "raw_gnss_observation_only",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
    }
