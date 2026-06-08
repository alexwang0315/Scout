from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


I2C_SLAVE = 0x0703
ICM20600_DEFAULT_ADDRESS = 0x69
AK09918_DEFAULT_ADDRESS = 0x0C

ICM20600_WHO_AM_I = 0x75
ICM20600_PWR_MGMT_1 = 0x6B
ICM20600_GYRO_CONFIG = 0x1B
ICM20600_ACCEL_CONFIG = 0x1C
ICM20600_ACCEL_XOUT_H = 0x3B

AK09918_WIA1 = 0x00
AK09918_ST1 = 0x10
AK09918_HXL = 0x11
AK09918_CNTL2 = 0x31


class I2cBus:
    def __init__(self, bus: Path) -> None:
        self.bus = bus

    def read_register(self, address: int, register: int, length: int) -> bytes:
        fd = os.open(self.bus, os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, address)
            os.write(fd, bytes([register]))
            return os.read(fd, length)
        finally:
            os.close(fd)

    def write_register(self, address: int, register: int, value: int) -> None:
        fd = os.open(self.bus, os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, address)
            os.write(fd, bytes([register, value]))
        finally:
            os.close(fd)


def parse_address(value: str) -> int:
    address = int(value, 0)
    if not 0x03 <= address <= 0x77:
        raise argparse.ArgumentTypeError("I2C address must be between 0x03 and 0x77")
    return address


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def read_live_imu_payload(
    *,
    bus: Path,
    imu_address: int,
    mag_address: int,
    sample_count: int,
    sample_interval_ms: float,
) -> dict[str, Any]:
    i2c = I2cBus(bus)
    imu_whoami = i2c.read_register(imu_address, ICM20600_WHO_AM_I, 1).hex()
    i2c.write_register(imu_address, ICM20600_PWR_MGMT_1, 0x01)
    i2c.write_register(imu_address, ICM20600_ACCEL_CONFIG, 0x00)
    i2c.write_register(imu_address, ICM20600_GYRO_CONFIG, 0x00)
    time.sleep(0.1)

    mag_wia: str | None = None
    mag_error: str | None = None
    try:
        mag_wia = i2c.read_register(mag_address, AK09918_WIA1, 2).hex()
    except Exception as exc:
        mag_error = f"{type(exc).__name__}: {exc}"

    samples: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    if mag_error is not None:
        provider_errors.append(f"mag_identity: {mag_error}")

    for sequence in range(sample_count):
        if sequence > 0 and sample_interval_ms > 0:
            time.sleep(sample_interval_ms / 1000.0)
        imu_raw = i2c.read_register(imu_address, ICM20600_ACCEL_XOUT_H, 14)
        sample = decode_imu_sample(imu_raw, sequence=sequence)
        try:
            sample.update(read_magnetometer_sample(i2c, mag_address))
        except Exception as exc:
            provider_errors.append(f"mag_sample_{sequence}: {type(exc).__name__}: {exc}")
            sample.update(
                {
                    "mag_status": "error",
                    "mag_st1": None,
                    "mag_raw": None,
                }
            )
        samples.append(sample)

    return build_payload(
        bus=bus,
        imu_address=imu_address,
        mag_address=mag_address,
        imu_whoami=f"0x{imu_whoami}",
        mag_wia=f"0x{mag_wia}" if mag_wia is not None else None,
        sample_count=sample_count,
        sample_interval_ms=sample_interval_ms,
        samples=samples,
        read_status="ok" if not provider_errors else "partial",
        dry_run=False,
        provider_errors=provider_errors,
    )


def read_magnetometer_sample(i2c: I2cBus, mag_address: int) -> dict[str, Any]:
    i2c.write_register(mag_address, AK09918_CNTL2, 0x01)
    time.sleep(0.02)
    st1 = i2c.read_register(mag_address, AK09918_ST1, 1)[0]
    raw = i2c.read_register(mag_address, AK09918_HXL, 8)
    return {
        "mag_status": "ok",
        "mag_st1": st1,
        "mag_raw": [
            signed16_le(raw[0], raw[1]),
            signed16_le(raw[2], raw[3]),
            signed16_le(raw[4], raw[5]),
        ],
    }


def decode_imu_sample(raw: bytes, *, sequence: int) -> dict[str, Any]:
    if len(raw) != 14:
        raise ValueError(f"ICM20600 sample must be 14 bytes, got {len(raw)}")
    values = [signed16_be(raw[index], raw[index + 1]) for index in range(0, 14, 2)]
    ax, ay, az, temperature_raw, gx, gy, gz = values
    return {
        "sequence": sequence,
        "accel_raw": [ax, ay, az],
        "gyro_raw": [gx, gy, gz],
        "temperature_raw": temperature_raw,
        "accel_g": [round(ax / 16384.0, 4), round(ay / 16384.0, 4), round(az / 16384.0, 4)],
        "gyro_dps": [round(gx / 131.0, 4), round(gy / 131.0, 4), round(gz / 131.0, 4)],
    }


def dry_run_payload(
    *,
    bus: Path,
    imu_address: int,
    mag_address: int,
    sample_count: int,
    sample_interval_ms: float,
) -> dict[str, Any]:
    sample = {
        "sequence": 0,
        "accel_raw": [1144, -14076, 7716],
        "gyro_raw": [-144, -105, 30],
        "temperature_raw": 0,
        "accel_g": [0.0698, -0.8591, 0.4709],
        "gyro_dps": [-1.0992, -0.8015, 0.229],
        "mag_status": "ok",
        "mag_st1": 1,
        "mag_raw": [-78, 261, -113],
    }
    samples = [{**sample, "sequence": sequence} for sequence in range(sample_count)]
    return build_payload(
        bus=bus,
        imu_address=imu_address,
        mag_address=mag_address,
        imu_whoami="0x11",
        mag_wia="0x480c",
        sample_count=sample_count,
        sample_interval_ms=sample_interval_ms,
        samples=samples,
        read_status="dry_run",
        dry_run=True,
        provider_errors=[],
    )


def build_payload(
    *,
    bus: Path,
    imu_address: int,
    mag_address: int,
    imu_whoami: str | None,
    mag_wia: str | None,
    sample_count: int,
    sample_interval_ms: float,
    samples: list[dict[str, Any]],
    read_status: str,
    dry_run: bool,
    provider_errors: list[str],
) -> dict[str, Any]:
    raw_magnetometer_present = any(sample.get("mag_status") == "ok" for sample in samples)
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_grove_imu_9dof_smoke",
        "hardware_kind": "grove_imu_9dof_icm20600_ak09918",
        "bus": str(bus),
        "imu_address": f"0x{imu_address:02x}",
        "mag_address": f"0x{mag_address:02x}",
        "imu_whoami": imu_whoami,
        "mag_wia": mag_wia,
        "read_status": read_status,
        "dry_run": dry_run,
        "sample_count": sample_count,
        "sample_interval_ms": sample_interval_ms,
        "scale_assumption": {
            "accel_lsb_per_g": 16384,
            "gyro_lsb_per_dps": 131,
            "accel_range": "+/-2g",
            "gyro_range": "+/-250dps",
        },
        "samples": samples,
        "raw_imu_present": bool(samples),
        "raw_magnetometer_present": raw_magnetometer_present,
        "primary_truth_allowed": False,
        "raw_evidence_required": True,
        "vendor_fusion_algorithm": "none",
        "replay_audit_supported": bool(samples),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_capture_only",
        "provider_errors": provider_errors,
    }


def error_payload(
    *,
    bus: Path,
    imu_address: int,
    mag_address: int,
    sample_count: int,
    sample_interval_ms: float,
    dry_run: bool,
    error: Exception,
) -> dict[str, Any]:
    payload = build_payload(
        bus=bus,
        imu_address=imu_address,
        mag_address=mag_address,
        imu_whoami=None,
        mag_wia=None,
        sample_count=sample_count,
        sample_interval_ms=sample_interval_ms,
        samples=[],
        read_status="error",
        dry_run=dry_run,
        provider_errors=[f"{type(error).__name__}: {error}"],
    )
    payload["error"] = f"{type(error).__name__}: {error}"
    return payload


def signed16_be(high: int, low: int) -> int:
    value = (high << 8) | low
    return value - 65536 if value & 0x8000 else value


def signed16_le(low: int, high: int) -> int:
    return signed16_be(high, low)


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Grove IMU 9DOF ICM20600 + AK09918 over Linux I2C.")
    parser.add_argument("--bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--imu-address", type=parse_address, default=ICM20600_DEFAULT_ADDRESS)
    parser.add_argument("--mag-address", type=parse_address, default=AK09918_DEFAULT_ADDRESS)
    parser.add_argument("--sample-count", type=parse_positive_int, default=5)
    parser.add_argument("--sample-interval-ms", type=parse_non_negative_float, default=100.0)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = (
            dry_run_payload(
                bus=args.bus,
                imu_address=args.imu_address,
                mag_address=args.mag_address,
                sample_count=args.sample_count,
                sample_interval_ms=args.sample_interval_ms,
            )
            if args.dry_run
            else read_live_imu_payload(
                bus=args.bus,
                imu_address=args.imu_address,
                mag_address=args.mag_address,
                sample_count=args.sample_count,
                sample_interval_ms=args.sample_interval_ms,
            )
        )
        append_jsonl(payload, args.output_jsonl)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = error_payload(
            bus=args.bus,
            imu_address=args.imu_address,
            mag_address=args.mag_address,
            sample_count=args.sample_count,
            sample_interval_ms=args.sample_interval_ms,
            dry_run=args.dry_run,
            error=exc,
        )
        append_jsonl(payload, args.output_jsonl)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
