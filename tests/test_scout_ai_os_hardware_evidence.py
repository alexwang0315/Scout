from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout.cli.hardware_evidence import main as hardware_evidence_main
from scout.hardware import (
    build_hardware_evidence_directory,
    build_hardware_evidence,
    host_probe_to_samples,
    load_hardware_evidence_samples,
    nmea_lines_to_samples,
    run_hardware_smoke,
    sensor_logger_json_to_samples,
    sensor_logger_rows_to_samples,
    write_hardware_evidence,
    write_hardware_evidence_directory,
)


ROOT = Path(__file__).resolve().parents[1]


def _sample() -> dict[str, object]:
    return {
        "sample_id": "sample-location-1",
        "source_kind": "mobile_sensor",
        "captured_at": "2026-06-08T00:00:00+00:00",
        "values": {"lat": 25.033, "lon": 121.5654, "accuracy_m": 7.5},
        "units": {"accuracy_m": "m"},
        "quality": {"fix": "candidate"},
        "provenance": {"transport": "sensor_logger_pro_mqtt"},
    }


def test_hardware_evidence_builder_stays_advisory_and_smoke_accepted(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "hardware-evidence.json"
    artifact = build_hardware_evidence(
        source="sensor_logger_pro_mqtt",
        source_device_id="iphone-test-device",
        samples=[_sample()],
        notes=["fixture-backed producer smoke"],
    )

    write_hardware_evidence(artifact, evidence_path)
    report = run_hardware_smoke(repo_root=ROOT, evidence_json=evidence_path)
    checks = {check.check_id: check for check in report.checks}

    assert artifact.boundary["advisory_only"] is True
    assert artifact.boundary["not_safety_truth"] is True
    assert artifact.boundary["runtime_ingest_performed"] is False
    assert artifact.boundary["provider_values_are_scout_truth"] is False
    assert checks["hardware_evidence_boundary"].status == "passed"


def test_hardware_evidence_cli_writes_smoke_compatible_json(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.json"
    output_path = tmp_path / "evidence.json"
    sample_path.write_text(json.dumps(_sample()), encoding="utf-8")

    exit_code = hardware_evidence_main(
        [
            "--source",
            "sensor_logger_pro_mqtt",
            "--source-device-id",
            "iphone-test-device",
            "--sample-json",
            str(sample_path),
            "--output",
            str(output_path),
            "--note",
            "manual hardware smoke fixture",
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["artifact_kind"] == "scout_hardware_evidence.v0"
    assert payload["boundary"]["outbound_sent"] is False
    assert payload["samples"][0]["provenance"]["transport"] == "sensor_logger_pro_mqtt"


def test_hardware_evidence_loader_accepts_sample_lists(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.json"
    sample_path.write_text(json.dumps([_sample()]), encoding="utf-8")

    samples = load_hardware_evidence_samples(sample_path)

    assert len(samples) == 1
    assert samples[0].source_kind == "mobile_sensor"


def test_sensor_logger_json_rows_become_mobile_evidence() -> None:
    samples = sensor_logger_json_to_samples(
        {
            "rows": [
                {
                    "timestamp": "2026-06-08T12:00:00Z",
                    "latitude": "25.033",
                    "longitude": "121.5654",
                    "horizontalAccuracy": "5.5",
                    "accelerometerAccelerationX": "0.1",
                    "gyroRotationZ": "0.03",
                }
            ]
        }
    )

    assert len(samples) == 1
    assert samples[0].source_kind == "mobile_sensor"
    assert samples[0].values["lat"] == 25.033
    assert samples[0].values["lon"] == 121.5654
    assert samples[0].values["accuracy_m"] == 5.5
    assert samples[0].provenance["producer"] == "sensor_logger"


def test_sensor_logger_csv_rows_become_mobile_evidence() -> None:
    samples = sensor_logger_rows_to_samples(
        [
            {
                "time": "2026-06-08T12:00:01Z",
                "locationLatitude": "25.034",
                "locationLongitude": "121.566",
                "locationSpeed": "1.2",
            }
        ]
    )

    assert samples[0].values["speed_mps"] == 1.2
    assert samples[0].quality["row_index"] == 0


def test_nmea_lines_become_gnss_evidence() -> None:
    samples = nmea_lines_to_samples(
        [
            "$GPGGA,123519,2501.9800,N,12133.9240,E,1,08,0.9,12.3,M,46.9,M,,*47",
            "$GPRMC,123520,A,2501.9801,N,12133.9241,E,1.5,84.4,080626,,,A*68",
        ]
    )

    assert len(samples) == 2
    assert samples[0].source_kind == "gnss"
    assert round(samples[0].values["lat"], 6) == 25.033
    assert round(samples[0].values["lon"], 6) == 121.5654
    assert samples[1].values["speed_knots"] == 1.5


def test_host_probe_and_directory_index_stay_advisory(tmp_path: Path) -> None:
    output_path = tmp_path / "evidence.json"
    index_path = tmp_path / "evidence-directory.json"
    samples = host_probe_to_samples(
        {
            "captured_at": "2026-06-08T12:00:02Z",
            "hostname": "scout.local",
            "uptime_seconds": 42,
            "services": [{"name": "scout-ai-os", "status": "active"}],
        }
    )
    artifact = build_hardware_evidence(
        source="scout_host_probe",
        source_device_id="scout.local",
        samples=samples,
    )
    directory = build_hardware_evidence_directory(
        root=tmp_path,
        artifacts=[(artifact, output_path)],
    )

    write_hardware_evidence(artifact, output_path)
    write_hardware_evidence_directory(directory, index_path)
    payload = json.loads(index_path.read_text(encoding="utf-8"))

    assert payload["artifact_kind"] == "scout_hardware_evidence_directory.v0"
    assert payload["boundary"]["runtime_ingest_performed"] is False
    assert payload["entries"][0]["source"] == "scout_host_probe"
    assert payload["entries"][0]["sample_count"] == 1


def test_hardware_evidence_cli_supports_sensor_logger_json_and_directory(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "sensor-logger.json"
    evidence_dir = tmp_path / "evidence"
    sample_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "timestamp": "2026-06-08T12:00:00Z",
                        "latitude": "25.033",
                        "longitude": "121.5654",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = hardware_evidence_main(
        [
            "--source",
            "sensor_logger_local_export",
            "--source-format",
            "sensor-logger-json",
            "--sample-json",
            str(sample_path),
            "--evidence-dir",
            str(evidence_dir),
        ]
    )

    index_payload = json.loads(
        (evidence_dir / "evidence-directory.json").read_text(encoding="utf-8")
    )
    artifact_path = evidence_dir / index_payload["entries"][0]["artifact_path"]
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert artifact_payload["samples"][0]["provenance"]["producer"] == "sensor_logger"
    assert index_payload["boundary"]["provider_values_are_scout_truth"] is False


def test_hardware_evidence_rejects_forbidden_true_boundary() -> None:
    with pytest.raises(ValueError, match="runtime effects"):
        build_hardware_evidence(
            source="bad_probe",
            samples=[_sample()],
            boundary_overrides={"safety_api_called": True},
        )
