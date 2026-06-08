from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiwonder_imu_frame_parser import frame_from_hex, parse_hiwonder_imu_frames  # noqa: E402


FUSED_FRAME_CODES = {0x56, 0x57, 0x58, 0x59, 0x5A, 0x5B, 0x5C}
NMEA_PATTERN = re.compile(rb"\$(?:GP|GN|GB|GA|GL)[A-Z]{3},[^\r\n]*")
FUSED_TEXT_PATTERN = re.compile(rb"(INS|FUS|PDOP|HDOP|ACCURACY|LAT|LON)", re.IGNORECASE)


def classify_vendor_fusion_stream(data: bytes) -> dict[str, Any]:
    frames = parse_hiwonder_imu_frames(data)
    known_imu_frames = [frame for frame in frames if frame.frame_type in {"acceleration", "gyro", "angle"}]
    fused_frames = [
        frame
        for frame in frames
        if len(frame.raw_bytes) > 1 and frame.raw_bytes[1] in FUSED_FRAME_CODES
    ]
    raw_gnss_sentences = [match.group(0).decode("ascii", errors="replace") for match in NMEA_PATTERN.finditer(data)]
    fused_text_present = bool(FUSED_TEXT_PATTERN.search(data))

    raw_imu_present = bool(known_imu_frames)
    raw_gnss_present = bool(raw_gnss_sentences)
    fused_navigation_present = bool(fused_frames or fused_text_present)
    mode = _classify_mode(
        raw_imu_present=raw_imu_present,
        raw_gnss_present=raw_gnss_present,
        fused_navigation_present=fused_navigation_present,
    )

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_imu_gnss_vendor_fusion_smoke",
        "hardware_kind": "hiwonder_wit_imu_gnss_vendor_fusion_observer",
        "vendor_fusion_mode_observed": mode,
        "raw_imu_present": raw_imu_present,
        "raw_gnss_present": raw_gnss_present,
        "fused_navigation_present": fused_navigation_present,
        "preferred_low_power_estimate": mode in {"imu_and_vendor_fused", "imu_with_gps_fields"},
        "primary_truth_allowed": False,
        "raw_evidence_required": True,
        "vendor_fusion_algorithm": "opaque",
        "replay_audit_supported": raw_imu_present or raw_gnss_present,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_capture_only",
        "observed_frame_types": [frame.frame_type for frame in frames],
        "raw_gnss_sentence_count": len(raw_gnss_sentences),
        "raw_gnss_sentences_sample": raw_gnss_sentences[:3],
        "fused_frame_count": len(fused_frames),
    }


def read_serial_bytes(*, port: str, baud: int, duration_seconds: float) -> bytes:
    try:
        import serial  # type: ignore
    except ImportError:
        return _read_serial_bytes_stdlib(port=port, baud=baud, duration_seconds=duration_seconds)

    chunks: list[bytes] = []
    deadline = time.monotonic() + duration_seconds
    with serial.Serial(port=port, baudrate=baud, timeout=0.1) as serial_port:
        while time.monotonic() < deadline:
            chunk = serial_port.read(512)
            if chunk:
                chunks.append(chunk)
    return b"".join(chunks)


def _read_serial_bytes_stdlib(*, port: str, baud: int, duration_seconds: float) -> bytes:
    import os
    import select
    import termios

    baud_constant = _termios_baud_constant(baud)
    chunks: list[bytes] = []
    deadline = time.monotonic() + duration_seconds
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = termios.IGNPAR
        attrs[1] = 0
        attrs[2] = baud_constant | termios.CS8 | termios.CLOCAL | termios.CREAD
        attrs[3] = 0
        attrs[4] = baud_constant
        attrs[5] = baud_constant
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)

        while time.monotonic() < deadline:
            timeout = max(0.0, min(0.1, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                continue
            chunk = os.read(fd, 512)
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _termios_baud_constant(baud: int) -> int:
    import termios

    constant_name = f"B{baud}"
    if not hasattr(termios, constant_name):
        raise RuntimeError(f"unsupported serial baud rate for stdlib fallback: {baud}")
    return getattr(termios, constant_name)


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _classify_mode(
    *,
    raw_imu_present: bool,
    raw_gnss_present: bool,
    fused_navigation_present: bool,
) -> str:
    if raw_imu_present and fused_navigation_present:
        return "imu_and_vendor_fused"
    if raw_imu_present and raw_gnss_present:
        return "imu_with_gps_fields"
    if raw_gnss_present and not raw_imu_present and not fused_navigation_present:
        return "gps_raw_only"
    if raw_imu_present and not raw_gnss_present and not fused_navigation_present:
        return "imu_only"
    if fused_navigation_present and not raw_imu_present and not raw_gnss_present:
        return "vendor_fused_only"
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify IMU/GNSS vendor fusion serial output mode.")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--duration-seconds", type=float, default=5.0)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--raw-hex", help="Parse fixture bytes from hex instead of opening serial.")
    parser.add_argument("--raw-text", help="Parse fixture text instead of opening serial.")
    args = parser.parse_args(argv)

    try:
        if args.raw_hex is not None:
            data = frame_from_hex(args.raw_hex)
        elif args.raw_text is not None:
            data = args.raw_text.encode("ascii", errors="replace")
        else:
            data = read_serial_bytes(port=args.port, baud=args.baud, duration_seconds=args.duration_seconds)
        payload = classify_vendor_fusion_stream(data)
        payload["device_port"] = args.port
        payload["baud"] = args.baud
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    append_jsonl(payload, args.output_jsonl)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
