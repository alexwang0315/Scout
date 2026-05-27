from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FRAME_LENGTH = 11
FRAME_HEADER = 0x55

FRAME_TYPES = {
    0x51: "acceleration",
    0x52: "gyro",
    0x53: "angle",
}


@dataclass(frozen=True)
class HiwonderImuFrame:
    frame_type: str
    raw_bytes: bytes
    checksum_valid: bool
    acceleration_g: tuple[float, float, float] | None = None
    angular_velocity_dps: tuple[float, float, float] | None = None
    angle_deg: tuple[float, float, float] | None = None

    @property
    def raw_bytes_hex(self) -> str:
        return self.raw_bytes.hex()

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "raw_bytes_hex": self.raw_bytes_hex,
            "acceleration_g": _tuple_or_none(self.acceleration_g),
            "angular_velocity_dps": _tuple_or_none(self.angular_velocity_dps),
            "angle_deg": _tuple_or_none(self.angle_deg),
            "checksum_valid": self.checksum_valid,
        }


class HiwonderImuStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[HiwonderImuFrame]:
        self._buffer.extend(data)
        frames: list[HiwonderImuFrame] = []
        while True:
            try:
                header_index = self._buffer.index(FRAME_HEADER)
            except ValueError:
                self._buffer.clear()
                break
            if header_index:
                del self._buffer[:header_index]
            if len(self._buffer) < FRAME_LENGTH:
                break
            frame_bytes = bytes(self._buffer[:FRAME_LENGTH])
            del self._buffer[:FRAME_LENGTH]
            frames.append(parse_hiwonder_imu_frame(frame_bytes))
        return frames


def parse_hiwonder_imu_frame(frame: bytes) -> HiwonderImuFrame:
    if len(frame) != FRAME_LENGTH:
        raise ValueError(f"WIT/JY901 frame must be {FRAME_LENGTH} bytes")
    if frame[0] != FRAME_HEADER:
        raise ValueError("WIT/JY901 frame must start with 0x55")

    checksum_valid = validate_checksum(frame)
    frame_code = frame[1]
    frame_type = FRAME_TYPES.get(frame_code, f"unknown_0x{frame_code:02x}")

    if frame_code == 0x51:
        return HiwonderImuFrame(
            frame_type=frame_type,
            raw_bytes=frame,
            checksum_valid=checksum_valid,
            acceleration_g=_scaled_xyz(frame, scale=16.0),
        )
    if frame_code == 0x52:
        return HiwonderImuFrame(
            frame_type=frame_type,
            raw_bytes=frame,
            checksum_valid=checksum_valid,
            angular_velocity_dps=_scaled_xyz(frame, scale=2000.0),
        )
    if frame_code == 0x53:
        return HiwonderImuFrame(
            frame_type=frame_type,
            raw_bytes=frame,
            checksum_valid=checksum_valid,
            angle_deg=_scaled_xyz(frame, scale=180.0),
        )
    return HiwonderImuFrame(
        frame_type=frame_type,
        raw_bytes=frame,
        checksum_valid=checksum_valid,
    )


def parse_hiwonder_imu_frames(data: bytes) -> list[HiwonderImuFrame]:
    return HiwonderImuStreamParser().feed(data)


def validate_checksum(frame: bytes) -> bool:
    if len(frame) != FRAME_LENGTH:
        return False
    return (sum(frame[:10]) & 0xFF) == frame[10]


def frame_from_hex(raw_hex: str) -> bytes:
    compact = "".join(raw_hex.replace("0x", "").split())
    return bytes.fromhex(compact)


def _scaled_xyz(frame: bytes, *, scale: float) -> tuple[float, float, float]:
    return tuple(round(_signed_int16_le(frame[index : index + 2]) / 32768.0 * scale, 6) for index in (2, 4, 6))


def _signed_int16_le(raw: bytes) -> int:
    return int.from_bytes(raw, byteorder="little", signed=True)


def _tuple_or_none(value: tuple[float, float, float] | None) -> list[float] | None:
    return list(value) if value is not None else None
