from hiwonder_imu_frame_parser import (
    frame_from_hex,
    parse_hiwonder_imu_frame,
    parse_hiwonder_imu_frames,
    validate_checksum,
)


def test_parse_acceleration_frame_and_checksum() -> None:
    frame = _wit_frame(0x51, [2048, -2048, 0, 2500])

    parsed = parse_hiwonder_imu_frame(frame)

    assert parsed.frame_type == "acceleration"
    assert parsed.checksum_valid is True
    assert parsed.acceleration_g == (1.0, -1.0, 0.0)
    assert parsed.angular_velocity_dps is None
    assert parsed.raw_bytes_hex == frame.hex()


def test_parse_gyro_and_angle_frames() -> None:
    gyro = parse_hiwonder_imu_frame(_wit_frame(0x52, [3277, -3277, 0, 0]))
    angle = parse_hiwonder_imu_frame(_wit_frame(0x53, [16384, -16384, 0, 0]))

    assert gyro.frame_type == "gyro"
    assert gyro.angular_velocity_dps == (200.012207, -200.012207, 0.0)
    assert angle.frame_type == "angle"
    assert angle.angle_deg == (90.0, -90.0, 0.0)


def test_invalid_checksum_is_preserved_on_parsed_frame() -> None:
    frame = bytearray(_wit_frame(0x51, [2048, 0, 0, 0]))
    frame[-1] ^= 0xFF

    parsed = parse_hiwonder_imu_frame(bytes(frame))

    assert validate_checksum(bytes(frame)) is False
    assert parsed.frame_type == "acceleration"
    assert parsed.checksum_valid is False
    assert parsed.raw_bytes_hex == bytes(frame).hex()


def test_unknown_frame_is_preserved_as_raw_evidence() -> None:
    frame = _wit_frame(0x58, [1, 2, 3, 4])

    parsed = parse_hiwonder_imu_frame(frame)

    assert parsed.frame_type == "unknown_0x58"
    assert parsed.checksum_valid is True
    assert parsed.acceleration_g is None
    assert parsed.raw_bytes_hex == frame.hex()


def test_parse_stream_skips_noise_and_handles_raw_hex() -> None:
    frame = _wit_frame(0x51, [2048, 0, 0, 0])

    parsed = parse_hiwonder_imu_frames(b"noise" + frame_from_hex(frame.hex()))

    assert len(parsed) == 1
    assert parsed[0].frame_type == "acceleration"


def _wit_frame(frame_type: int, values: list[int]) -> bytes:
    payload = b"".join(value.to_bytes(2, "little", signed=True) for value in values)
    frame = bytes([0x55, frame_type]) + payload
    return frame + bytes([sum(frame) & 0xFF])
