from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


I2C_SLAVE = 0x0703
DEFAULT_MESSAGE = "SCOUT\nI2C OK\n0x3C"
SSD1327_DISPLAY_WIDTH = 96
SSD1327_DISPLAY_HEIGHT = 96
SH1107G_DISPLAY_WIDTH = 128
SH1107G_DISPLAY_HEIGHT = 128
DISPLAY_WIDTH = SSD1327_DISPLAY_WIDTH
DISPLAY_HEIGHT = SSD1327_DISPLAY_HEIGHT
DISPLAY_GEOMETRIES = {
    "ssd1327": (SSD1327_DISPLAY_WIDTH, SSD1327_DISPLAY_HEIGHT),
    "sh1107g": (SH1107G_DISPLAY_WIDTH, SH1107G_DISPLAY_HEIGHT),
}

FONT_5X7 = {
    " ": [0x00, 0x00, 0x00, 0x00, 0x00],
    "-": [0x08, 0x08, 0x08, 0x08, 0x08],
    ".": [0x00, 0x60, 0x60, 0x00, 0x00],
    ":": [0x00, 0x36, 0x36, 0x00, 0x00],
    "0": [0x3E, 0x51, 0x49, 0x45, 0x3E],
    "1": [0x00, 0x42, 0x7F, 0x40, 0x00],
    "2": [0x42, 0x61, 0x51, 0x49, 0x46],
    "3": [0x21, 0x41, 0x45, 0x4B, 0x31],
    "4": [0x18, 0x14, 0x12, 0x7F, 0x10],
    "5": [0x27, 0x45, 0x45, 0x45, 0x39],
    "6": [0x3C, 0x4A, 0x49, 0x49, 0x30],
    "7": [0x01, 0x71, 0x09, 0x05, 0x03],
    "8": [0x36, 0x49, 0x49, 0x49, 0x36],
    "9": [0x06, 0x49, 0x49, 0x29, 0x1E],
    "A": [0x7E, 0x11, 0x11, 0x11, 0x7E],
    "B": [0x7F, 0x49, 0x49, 0x49, 0x36],
    "C": [0x3E, 0x41, 0x41, 0x41, 0x22],
    "D": [0x7F, 0x41, 0x41, 0x22, 0x1C],
    "E": [0x7F, 0x49, 0x49, 0x49, 0x41],
    "F": [0x7F, 0x09, 0x09, 0x09, 0x01],
    "G": [0x3E, 0x41, 0x49, 0x49, 0x7A],
    "H": [0x7F, 0x08, 0x08, 0x08, 0x7F],
    "I": [0x00, 0x41, 0x7F, 0x41, 0x00],
    "J": [0x20, 0x40, 0x41, 0x3F, 0x01],
    "K": [0x7F, 0x08, 0x14, 0x22, 0x41],
    "L": [0x7F, 0x40, 0x40, 0x40, 0x40],
    "M": [0x7F, 0x02, 0x0C, 0x02, 0x7F],
    "N": [0x7F, 0x04, 0x08, 0x10, 0x7F],
    "O": [0x3E, 0x41, 0x41, 0x41, 0x3E],
    "P": [0x7F, 0x09, 0x09, 0x09, 0x06],
    "Q": [0x3E, 0x41, 0x51, 0x21, 0x5E],
    "R": [0x7F, 0x09, 0x19, 0x29, 0x46],
    "S": [0x46, 0x49, 0x49, 0x49, 0x31],
    "T": [0x01, 0x01, 0x7F, 0x01, 0x01],
    "U": [0x3F, 0x40, 0x40, 0x40, 0x3F],
    "V": [0x1F, 0x20, 0x40, 0x20, 0x1F],
    "W": [0x7F, 0x20, 0x18, 0x20, 0x7F],
    "X": [0x63, 0x14, 0x08, 0x14, 0x63],
    "Y": [0x07, 0x08, 0x70, 0x08, 0x07],
    "Z": [0x61, 0x51, 0x49, 0x45, 0x43],
}


class I2cDevice:
    def __init__(self, bus: Path, address: int) -> None:
        self._fd = os.open(bus, os.O_RDWR)
        fcntl.ioctl(self._fd, I2C_SLAVE, address)

    def write_command(self, *commands: int) -> None:
        if not commands:
            return
        os.write(self._fd, bytes([0x00, *commands]))

    def write_data(self, data: bytes) -> None:
        for offset in range(0, len(data), 16):
            os.write(self._fd, bytes([0x40]) + data[offset : offset + 16])

    def close(self) -> None:
        os.close(self._fd)


def parse_address(value: str) -> int:
    address = int(value, 0)
    if not 0x03 <= address <= 0x77:
        raise argparse.ArgumentTypeError("I2C address must be between 0x03 and 0x77")
    return address


def render_message_buffer(
    message: str,
    *,
    width: int = DISPLAY_WIDTH,
    height: int = DISPLAY_HEIGHT,
) -> list[int]:
    pages = height // 8
    buffer = [0x00] * (width * pages)
    max_lines = max(1, pages // 2)
    max_chars = max(1, width // 6)
    for line_index, line in enumerate(message.upper().splitlines()[:max_lines]):
        y_page = line_index * 2
        if y_page >= pages:
            break
        x = 0
        for char in line[:max_chars]:
            glyph = FONT_5X7.get(char, FONT_5X7[" "])
            for column in glyph + [0x00]:
                if x < width:
                    buffer[y_page * width + x] = column
                x += 1
    return buffer


def write_sh1107g(device: I2cDevice, message: str) -> None:
    device.write_command(0xAE)
    device.write_command(0xD5, 0x50)
    device.write_command(0x20)
    device.write_command(0x81, 0x80)
    device.write_command(0xA0)
    device.write_command(0xA4)
    device.write_command(0xA6)
    device.write_command(0xAD, 0x80)
    device.write_command(0xC0)
    device.write_command(0xD9, 0x1F)
    device.write_command(0xDB, 0x27)
    device.write_command(0xAF)
    device.write_command(0xB0)
    device.write_command(0x00)
    device.write_command(0x11)
    _write_monochrome_pages(
        device,
        render_message_buffer(
            message,
            width=SH1107G_DISPLAY_WIDTH,
            height=SH1107G_DISPLAY_HEIGHT,
        ),
        width=SH1107G_DISPLAY_WIDTH,
        height=SH1107G_DISPLAY_HEIGHT,
    )


def write_ssd1327(device: I2cDevice, message: str) -> None:
    device.write_command(0xAE)
    device.write_command(0xA0, 0x51)
    device.write_command(0xA1, 0x00)
    device.write_command(0xA2, 0x00)
    device.write_command(0xAB, 0x01)
    device.write_command(0xAF)
    _write_monochrome_pages(
        device,
        render_message_buffer(
            message,
            width=SSD1327_DISPLAY_WIDTH,
            height=SSD1327_DISPLAY_HEIGHT,
        ),
        width=SSD1327_DISPLAY_WIDTH,
        height=SSD1327_DISPLAY_HEIGHT,
    )


def _write_monochrome_pages(
    device: I2cDevice,
    buffer: list[int],
    *,
    width: int,
    height: int,
) -> None:
    pages = height // 8
    for page in range(pages):
        device.write_command(0xB0 + page)
        device.write_command(0x00)
        device.write_command(0x10)
        start = page * width
        device.write_data(bytes(buffer[start : start + width]))


def display_geometry_for_driver(driver_attempted: str) -> tuple[int, int] | None:
    driver = driver_attempted.split(":", 1)[-1]
    return DISPLAY_GEOMETRIES.get(driver)


def build_payload(
    *,
    bus: Path,
    address: int,
    driver_attempted: str,
    write_status: str,
    message: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_oled_i2c_smoke",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "message": message,
        "dry_run": dry_run,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if error is not None:
        payload["error"] = error
    geometry = display_geometry_for_driver(driver_attempted)
    if geometry is not None:
        payload["display_width"] = geometry[0]
        payload["display_height"] = geometry[1]
    return payload


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_display(*, bus: Path, address: int, driver: str, message: str) -> str:
    if driver == "auto":
        last_error: Exception | None = None
        for candidate in ("sh1107g", "ssd1327"):
            try:
                write_display(bus=bus, address=address, driver=candidate, message=message)
                return f"auto:{candidate}"
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    device = I2cDevice(bus, address)
    try:
        if driver == "sh1107g":
            write_sh1107g(device, message)
        elif driver == "ssd1327":
            write_ssd1327(device, message)
        else:
            raise ValueError(f"unsupported OLED driver: {driver}")
    finally:
        device.close()
    return driver


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a Grove 96x96 OLED through Linux I2C.")
    parser.add_argument("--bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--driver", choices=("sh1107g", "ssd1327", "auto"), default="auto")
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.dry_run:
            driver_attempted = args.driver
        else:
            driver_attempted = write_display(
                bus=args.bus,
                address=args.address,
                driver=args.driver,
                message=args.message,
            )
        payload = build_payload(
            bus=args.bus,
            address=args.address,
            driver_attempted=driver_attempted,
            write_status="dry_run" if args.dry_run else "ok",
            message=args.message,
            dry_run=args.dry_run,
        )
        append_jsonl(payload, args.output_jsonl)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = build_payload(
            bus=args.bus,
            address=args.address,
            driver_attempted=args.driver,
            write_status="error",
            message=args.message,
            dry_run=args.dry_run,
            error=f"{type(exc).__name__}: {exc}",
        )
        append_jsonl(payload, args.output_jsonl)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
