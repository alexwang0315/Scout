from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout.cli.hardware_evidence import main as hardware_evidence_main
from scout.hardware import (
    build_hardware_evidence,
    load_hardware_evidence_samples,
    run_hardware_smoke,
    write_hardware_evidence,
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


def test_hardware_evidence_rejects_forbidden_true_boundary() -> None:
    with pytest.raises(ValueError, match="runtime effects"):
        build_hardware_evidence(
            source="bad_probe",
            samples=[_sample()],
            boundary_overrides={"safety_api_called": True},
        )
