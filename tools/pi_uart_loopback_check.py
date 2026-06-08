from __future__ import annotations

import argparse
import json
import os
import select
import termios
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PAYLOAD = b"SCOUT_UART_LOOPBACK_0123456789\r\n"


def evaluate_loopback(
    *,
    port: str,
    baud: int,
    expected: bytes,
    observed: bytes,
    duration_seconds: float,
) -> dict[str, Any]:
    matched = expected in observed
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_uart_loopback_check",
        "hardware_kind": "uart_tx_rx_loopback",
        "hardware_control_scope": "diagnostic_uart_loopback_requires_gnss_disconnected",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "device_port": port,
        "baud": baud,
        "duration_seconds": duration_seconds,
        "expected_hex": expected.hex(),
        "observed_hex": observed.hex(),
        "observed_ascii": observed.decode("ascii", "replace"),
        "expected_bytes": len(expected),
        "observed_bytes": len(observed),
        "loopback_passed": matched,
        "summary": {
            "likely_state": "uart_tx_rx_loopback_passed" if matched else "uart_tx_rx_loopback_failed",
            "scout_uart_tx_rx_proven": matched,
            "next_step": _next_step(matched),
        },
    }


def run_loopback(
    *,
    port: str,
    baud: int,
    payload: bytes,
    duration_seconds: float,
) -> dict[str, Any]:
    observed = write_then_read_serial(port=port, baud=baud, payload=payload, duration_seconds=duration_seconds)
    return evaluate_loopback(
        port=port,
        baud=baud,
        expected=payload,
        observed=observed,
        duration_seconds=duration_seconds,
    )


def write_then_read_serial(*, port: str, baud: int, payload: bytes, duration_seconds: float) -> bytes:
    baud_constant = _termios_baud_constant(baud)
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
        attrs[6][termios.VTIME] = 2
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)

        os.write(fd, payload)
        chunks: list[bytes] = []
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            timeout = max(0.0, min(0.2, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                continue
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check Raspberry Pi UART TX/RX by requiring a physical TX-RX loopback jumper."
    )
    parser.add_argument("--port", default="/dev/ttyAMA0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--duration-seconds", type=float, default=2.0)
    parser.add_argument("--payload", default=DEFAULT_PAYLOAD.decode("ascii"))
    parser.add_argument("--output-json", type=Path)
    parser.add_argument(
        "--i-confirm-gnss-disconnected-and-tx-rx-shorted",
        action="store_true",
        help="Required before writing to UART. Disconnect GNSS and short Pi TXD0 to RXD0 first.",
    )
    parser.add_argument("--raw-observed-hex", help="Evaluate captured bytes without opening serial.")
    args = parser.parse_args(argv)

    expected = args.payload.encode("ascii")
    if args.raw_observed_hex is not None:
        payload = evaluate_loopback(
            port=args.port,
            baud=args.baud,
            expected=expected,
            observed=bytes.fromhex(args.raw_observed_hex),
            duration_seconds=args.duration_seconds,
        )
    else:
        if not args.i_confirm_gnss_disconnected_and_tx_rx_shorted:
            parser.error(
                "--i-confirm-gnss-disconnected-and-tx-rx-shorted is required before writing to UART"
            )
        payload = run_loopback(
            port=args.port,
            baud=args.baud,
            payload=expected,
            duration_seconds=args.duration_seconds,
        )

    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n")
    print(text)
    return 0


def _next_step(matched: bool) -> str:
    if matched:
        return "Scout UART TX/RX side is proven. If Grove still ignores PUBX/UBX, inspect Grove RX wire, level, pin mapping, or receiver input protocol."
    return "Check that GNSS is disconnected, GPIO14 TXD0 is shorted to GPIO15 RXD0, no serial owner is active, and /dev/ttyAMA0 is the correct UART."


def _termios_baud_constant(baud: int) -> int:
    constant_name = f"B{baud}"
    if not hasattr(termios, constant_name):
        raise RuntimeError(f"unsupported serial baud rate: {baud}")
    return getattr(termios, constant_name)


if __name__ == "__main__":
    raise SystemExit(main())
