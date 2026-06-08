from ins_dr_input_adapter import (
    InsDrInputState,
    dead_reckoning_delta_from_payload,
    gnss_fix_from_payload,
)


def test_gnss_payload_converts_to_fix_with_hdop_accuracy() -> None:
    payload = {
        "source": "pi_gnss_nmea_smoke",
        "timestamp_s": 12.0,
        "sentence_type": "GPGGA",
        "position": {"lat": 25.1, "lon": 121.2},
        "fix_quality": {"quality": 1, "valid": True, "satellites": 8, "hdop": 0.9},
        "raw_sentence": "$GPGGA,...",
    }

    fix = gnss_fix_from_payload(payload, fallback_timestamp_s=0.0)

    assert fix is not None
    assert fix.timestamp_s == 12.0
    assert fix.lat == 25.1
    assert fix.lon == 121.2
    assert fix.horizontal_accuracy_m == 4.5
    assert fix.fix_quality == 1
    assert fix.satellite_count == 8
    assert fix.raw_evidence_ref == "$GPGGA,..."


def test_gnss_payload_with_invalid_checksum_is_not_a_fix() -> None:
    payload = {
        "source": "pi_gnss_nmea_smoke",
        "timestamp_s": 12.0,
        "sentence_type": "GPGGA",
        "checksum_valid": False,
        "position": {"lat": 25.1, "lon": 121.2},
        "fix_quality": {"quality": 1, "valid": True, "satellites": 8, "hdop": 0.9},
        "raw_sentence": "$GPGGA,...*00",
    }

    assert gnss_fix_from_payload(payload, fallback_timestamp_s=0.0) is None


def test_hiwonder_angle_frame_updates_heading_for_next_direct_delta() -> None:
    state = InsDrInputState()

    heading_only = dead_reckoning_delta_from_payload(
        {
            "source": "pi_hiwonder_imu_usb_smoke",
            "timestamp_s": 1.0,
            "frame_type": "angle",
            "checksum_valid": True,
            "parsed": {"angle_deg": [1.0, 2.0, 93.0]},
            "raw_bytes_hex": "55530000000000000000a8",
        },
        state,
        fallback_timestamp_s=1.0,
    )
    delta = dead_reckoning_delta_from_payload(
        {
            "source": "wheel_odometry",
            "timestamp_s": 2.0,
            "distance_delta_m": 1.25,
            "raw_evidence_ref": "wheel.001",
        },
        state,
        fallback_timestamp_s=2.0,
    )

    assert heading_only is None
    assert state.last_heading_deg == 93.0
    assert delta is not None
    assert delta.distance_delta_m == 1.25
    assert delta.heading_deg == 93.0
    assert delta.raw_evidence_ref == "wheel.001"


def test_sensorlog_cumulative_pedometer_distance_becomes_delta_after_baseline() -> None:
    state = InsDrInputState()
    first = dead_reckoning_delta_from_payload(
        {"sensorlog": {"pedometerDistance": 100.0, "locationCourse": 30.0}},
        state,
        fallback_timestamp_s=10.0,
    )
    second = dead_reckoning_delta_from_payload(
        {"sensorlog": {"pedometerDistance": 106.5, "locationCourse": 35.0}},
        state,
        fallback_timestamp_s=20.0,
    )

    assert first is None
    assert second is not None
    assert second.timestamp_s == 20.0
    assert second.distance_delta_m == 6.5
    assert second.heading_deg == 35.0
    assert second.source == "sensorlog_pedometer_distance"
