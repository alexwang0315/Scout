from __future__ import annotations

import json
from datetime import datetime, timezone

from scout_hardware_readiness_live_probe import build_probe_result
from scout_runtime_safety_pi_live_qualification import (
    PiGnssObservation,
    PiRuntimeObservation,
    run_pi_live_qualification,
)


def _probe():
    return build_probe_result(
        "scout",
        """
__SCOUT_PROBE_SECTION__ host
host=scout
kernel=Linux 6.12 aarch64 GNU/Linux
user=scout
date=2026-08-31T12:00:00+08:00
__SCOUT_PROBE_SECTION__ gpio_tools
/usr/bin/gpioinfo
__SCOUT_PROBE_SECTION__ gpiodetect
gpiochip0 [pinctrl-rp1] (54 lines)
__SCOUT_PROBE_SECTION__ gpioinfo
gpiochip0 - 54 lines:
__SCOUT_PROBE_SECTION__ i2c
/dev/i2c-1
__SCOUT_PROBE_SECTION__ uart
/dev/ttyAMA0
__SCOUT_PROBE_SECTION__ lsblk_json
{"blockdevices":[{"name":"nvme0n1","type":"disk","size":"2T"}]}
""",
    )


def _runtime(**updates: object) -> PiRuntimeObservation:
    values: dict[str, object] = {
        "observed_at": "2026-08-31T04:00:00Z",
        "host": "scout",
        "architecture": "aarch64",
        "machine_identity_sha256": "a" * 64,
        "admin_container_running": True,
        "admin_container_health": "healthy",
        "mqtt_container_running": True,
        "gnss_observer_process_running": True,
        "gnss_observer_visual_control_configured": False,
        "gnss_observer_reported_hardware_control_allowed": False,
        "gnss_observer_reported_hardware_control_performed": False,
        "gnss_observer_updated_at": "2026-08-31T03:59:58Z",
        "gnss_selected_observed_at": "2026-06-16T02:18:30Z",
    }
    values.update(updates)
    return PiRuntimeObservation.model_validate(values)


def _no_stream() -> PiGnssObservation:
    return PiGnssObservation(
        status="blocked_no_nmea_stream",
        observed_at="2026-08-31T04:00:05Z",
        device_ref="device://scout/gnss",
        sentence_count=0,
        valid_fix_count=0,
        checksum_valid_count=0,
        checksum_invalid_count=0,
        read_only_hardware_access=True,
    )


def test_pi_live_qualification_binds_no_stream_and_rejects_stale_field_input() -> None:
    report = run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=_probe(),
        runtime=_runtime(),
        gnss=_no_stream(),
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )

    encoded = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert report.status == "pi_runtime_verified_field_input_blocked"
    assert report.pi_runtime_observed is True
    assert report.pi_device_identity_verified is True
    assert report.pi_hardware_fail_closed_verified is True
    assert report.pi_hardware_evidence_ready is True
    assert report.field_device_observation_observed is True
    assert report.device_or_field_evidence_bound is True
    assert report.disputed_validation_rejected is True
    assert report.field_device_validator_evidence_ready is True
    assert report.freshness_window_enforced is True
    assert report.stale_source_rejected is True
    assert report.resident_freshness_attestor_observed is False
    assert report.freshness_evidence_ready is False
    assert "lat" not in encoded
    assert "lon" not in encoded
    assert "raw_sentence" not in encoded


def test_pi_live_qualification_blocks_observer_control_boundary_mismatch() -> None:
    report = run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=_probe(),
        runtime=_runtime(
            gnss_observer_visual_control_configured=True,
            gnss_observer_reported_hardware_control_allowed=False,
            gnss_observer_reported_hardware_control_performed=False,
        ),
        gnss=_no_stream(),
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )

    assert report.status == "blocked_pi_control_boundary_mismatch"
    assert report.pi_hardware_fail_closed_verified is False
    assert report.pi_hardware_evidence_ready is False
    assert report.blockers == ["gnss_observer_hardware_control_boundary_mismatch"]


def test_pi_live_qualification_accepts_declared_resident_visual_control() -> None:
    report = run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=_probe(),
        runtime=_runtime(
            gnss_observer_visual_control_configured=True,
            gnss_observer_reported_hardware_control_allowed=True,
            gnss_observer_reported_hardware_control_performed=True,
        ),
        gnss=_no_stream(),
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )

    assert report.observer_hardware_control_boundary_mismatch is False
    assert report.pi_hardware_fail_closed_verified is True
    assert report.pi_hardware_evidence_ready is True
    assert report.qualification_hardware_control_performed is False


def test_pi_live_qualification_accepts_hashed_bounded_resident_attestor_evidence() -> None:
    report = run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=_probe(),
        runtime=_runtime(
            freshness_attestor_process_running=False,
            freshness_attestor_reported_resident_process_observed=True,
            freshness_attestor_status="freshness_attestation_complete",
            freshness_attestor_heartbeat_count=10,
            freshness_attestor_current_source_count=1,
            freshness_attestor_stale_source_rejected=True,
            freshness_attestor_status_sha256="b" * 64,
        ),
        gnss=_no_stream(),
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )

    assert report.resident_freshness_attestor_observed is True
    assert report.freshness_evidence_ready is True


def test_pi_live_qualification_rejects_process_name_without_attestor_receipt() -> None:
    report = run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=_probe(),
        runtime=_runtime(freshness_attestor_process_running=True),
        gnss=_no_stream(),
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )

    assert report.resident_freshness_attestor_observed is False
    assert report.freshness_evidence_ready is False


def test_pi_live_qualification_fails_when_admin_runtime_is_not_healthy() -> None:
    report = run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=_probe(),
        runtime=_runtime(admin_container_health="unhealthy"),
        gnss=_no_stream(),
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )

    assert report.status == "blocked_pi_runtime_unavailable"
    assert report.pi_runtime_observed is False
    assert report.pi_hardware_evidence_ready is False
