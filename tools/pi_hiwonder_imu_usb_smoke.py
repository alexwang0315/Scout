from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiwonder_imu_frame_parser import (  # noqa: E402
    HiwonderImuFrame,
    HiwonderImuStreamParser,
    frame_from_hex,
    parse_hiwonder_imu_frames,
)


def build_imu_payload(
    frame: HiwonderImuFrame,
    *,
    device_port: str,
    baud: int,
) -> dict[str, Any]:
    raw_imu_present = frame.frame_type in {"acceleration", "gyro", "angle"}
    parsed = frame.to_dict()
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_hiwonder_imu_usb_smoke",
        "hardware_kind": "hiwonder_wit_imu_usb",
        "device_port": device_port,
        "baud": baud,
        "frame_type": frame.frame_type,
        "parsed": parsed,
        "raw_bytes_hex": frame.raw_bytes_hex,
        "vendor_fusion_mode_observed": "imu_raw_frames" if raw_imu_present else "unknown_frame",
        "raw_imu_present": raw_imu_present,
        "raw_gnss_present": False,
        "fused_navigation_present": False,
        "preferred_low_power_estimate": False,
        "primary_truth_allowed": False,
        "raw_evidence_required": True,
        "vendor_fusion_algorithm": "opaque",
        "replay_audit_supported": raw_imu_present,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_capture_only",
    }


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def read_serial_frames(*, port: str, baud: int, duration_seconds: float) -> list[HiwonderImuFrame]:
    try:
        import serial  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on Pi environment.
        raise RuntimeError(
            "pyserial is required for live serial smoke: python3 -m pip install pyserial"
        ) from exc

    parser = HiwonderImuStreamParser()
    frames: list[HiwonderImuFrame] = []
    deadline = time.monotonic() + duration_seconds
    with serial.Serial(port=port, baudrate=baud, timeout=0.1) as serial_port:
        while time.monotonic() < deadline:
            chunk = serial_port.read(256)
            if chunk:
                frames.extend(parser.feed(chunk))
    return frames


def parse_raw_hex_frames(raw_hex: str) -> list[HiwonderImuFrame]:
    return parse_hiwonder_imu_frames(frame_from_hex(raw_hex))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read Hiwonder/WIT IMU USB serial frames as diagnostic evidence.")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--duration-seconds", type=float, default=5.0)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--raw-hex", help="Parse raw fixture bytes from hex instead of opening serial.")
    args = parser.parse_args(argv)

    try:
        frames = (
            parse_raw_hex_frames(args.raw_hex)
            if args.raw_hex is not None
            else read_serial_frames(port=args.port, baud=args.baud, duration_seconds=args.duration_seconds)
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    payloads = [build_imu_payload(frame, device_port=args.port, baud=args.baud) for frame in frames]
    append_jsonl(payloads, args.output_jsonl)
    print(json.dumps({"frames": payloads, "frame_count": len(payloads)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
