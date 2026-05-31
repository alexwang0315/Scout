from __future__ import annotations

import argparse
import json
import os
import select
import sys
import termios
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UBX_HEADER = b"\xb5\x62"
UBX_POLLS = {
    "MON-VER": (0x0A, 0x04),
    "CFG-ANT": (0x06, 0x13),
    "MON-HW": (0x0A, 0x09),
    "NAV-SVINFO": (0x01, 0x30),
    "RXM-SVSI": (0x02, 0x20),
    "NAV-STATUS": (0x01, 0x03),
    "NAV-SOL": (0x01, 0x06),
}
UBX_RESPONSE_KEYS = {
    (0x05, 0x00): "ACK-NAK",
    (0x05, 0x01): "ACK-ACK",
}
PUBX_POLLS = (
    b"$PUBX,00*33\r\n",
    b"$PUBX,03*30\r\n",
)
ANTENNA_STATUS = {
    0: "INIT",
    1: "DONTKNOW",
    2: "OK",
    3: "SHORT",
    4: "OPEN",
}
ANTENNA_POWER = {
    0: "OFF",
    1: "ON",
    2: "DONTKNOW",
}


@dataclass(frozen=True)
class UbxFrame:
    msg_class: int
    msg_id: int
    payload: bytes
    checksum_valid: bool
    raw_bytes: bytes

    @property
    def key(self) -> str:
        if (self.msg_class, self.msg_id) in UBX_RESPONSE_KEYS:
            return UBX_RESPONSE_KEYS[(self.msg_class, self.msg_id)]
        for name, (msg_class, msg_id) in UBX_POLLS.items():
            if (self.msg_class, self.msg_id) == (msg_class, msg_id):
                return name
        return f"0x{self.msg_class:02x}:0x{self.msg_id:02x}"


def ubx_checksum(body: bytes) -> tuple[int, int]:
    ck_a = 0
    ck_b = 0
    for value in body:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def build_ubx_poll(msg_class: int, msg_id: int) -> bytes:
    body = bytes([msg_class, msg_id, 0x00, 0x00])
    ck_a, ck_b = ubx_checksum(body)
    return UBX_HEADER + body + bytes([ck_a, ck_b])


def parse_ubx_frames(data: bytes) -> list[UbxFrame]:
    frames: list[UbxFrame] = []
    index = 0
    while True:
        start = data.find(UBX_HEADER, index)
        if start < 0:
            return frames
        if len(data) < start + 8:
            return frames

        msg_class = data[start + 2]
        msg_id = data[start + 3]
        payload_len = int.from_bytes(data[start + 4 : start + 6], "little")
        end = start + 8 + payload_len
        if len(data) < end:
            return frames

        payload = data[start + 6 : start + 6 + payload_len]
        raw = data[start:end]
        expected = raw[-2:]
        actual = bytes(ubx_checksum(raw[2:-2]))
        frames.append(
            UbxFrame(
                msg_class=msg_class,
                msg_id=msg_id,
                payload=payload,
                checksum_valid=expected == actual,
                raw_bytes=raw,
            )
        )
        index = end


def parse_mon_ver(payload: bytes) -> dict[str, Any]:
    if len(payload) < 40:
        return {"payload_length": len(payload), "parse_error": "payload shorter than MON-VER minimum"}
    extensions = []
    for offset in range(40, len(payload), 30):
        text = _cstring(payload[offset : offset + 30])
        if text:
            extensions.append(text)
    return {
        "software_version": _cstring(payload[0:30]),
        "hardware_version": _cstring(payload[30:40]),
        "extensions": extensions,
    }


def parse_mon_hw(payload: bytes) -> dict[str, Any]:
    if len(payload) < 22:
        return {"payload_length": len(payload), "parse_error": "payload shorter than MON-HW antenna fields"}
    antenna_status = payload[20]
    antenna_power = payload[21]
    return {
        "payload_length": len(payload),
        "noise_per_ms": int.from_bytes(payload[16:18], "little"),
        "agc_count": int.from_bytes(payload[18:20], "little"),
        "antenna_status": antenna_status,
        "antenna_status_label": ANTENNA_STATUS.get(antenna_status, f"UNKNOWN_{antenna_status}"),
        "antenna_power": antenna_power,
        "antenna_power_label": ANTENNA_POWER.get(antenna_power, f"UNKNOWN_{antenna_power}"),
    }


def parse_cfg_ant(payload: bytes) -> dict[str, Any]:
    if len(payload) < 4:
        return {"payload_length": len(payload), "parse_error": "payload shorter than CFG-ANT minimum"}
    flags = int.from_bytes(payload[0:2], "little")
    pins = int.from_bytes(payload[2:4], "little")
    known_flags = {
        "svcs": bool(flags & 0x0001),
        "scd": bool(flags & 0x0002),
        "ocd": bool(flags & 0x0004),
        "pdwn_on_scd": bool(flags & 0x0008),
        "recovery": bool(flags & 0x0010),
    }
    return {
        "payload_length": len(payload),
        "flags": flags,
        "pins": pins,
        "flags_decoded": known_flags,
        "unknown_flag_bits": flags & ~0x001F,
    }


def parse_nav_svinfo(payload: bytes) -> dict[str, Any]:
    if len(payload) < 8:
        return {"payload_length": len(payload), "parse_error": "payload shorter than NAV-SVINFO header"}
    num_channels = payload[4]
    channels = []
    for index in range(num_channels):
        offset = 8 + index * 12
        if len(payload) < offset + 12:
            break
        channels.append(
            {
                "channel": payload[offset],
                "svid": payload[offset + 1],
                "flags": payload[offset + 2],
                "quality": payload[offset + 3],
                "cno_dbhz": payload[offset + 4],
                "elevation_deg": int.from_bytes(payload[offset + 5 : offset + 6], "little", signed=True),
                "azimuth_deg": int.from_bytes(payload[offset + 6 : offset + 8], "little", signed=True),
                "pseudorange_residual_cm": int.from_bytes(payload[offset + 8 : offset + 12], "little", signed=True),
            }
        )
    cno_values = [channel["cno_dbhz"] for channel in channels]
    return {
        "payload_length": len(payload),
        "itow_ms": int.from_bytes(payload[0:4], "little"),
        "num_channels": num_channels,
        "parsed_channels": len(channels),
        "nonzero_cno_count": sum(1 for value in cno_values if value > 0),
        "max_cno_dbhz": max(cno_values) if cno_values else None,
        "channels": channels,
    }


def parse_rxm_svsi(payload: bytes) -> dict[str, Any]:
    if len(payload) < 8:
        return {"payload_length": len(payload), "parse_error": "payload shorter than RXM-SVSI header"}
    num_svs = payload[7]
    satellites = []
    for index in range(num_svs):
        offset = 8 + index * 6
        if len(payload) < offset + 6:
            break
        satellites.append(
            {
                "svid": payload[offset],
                "sv_flag": payload[offset + 1],
                "azimuth_deg": int.from_bytes(payload[offset + 2 : offset + 4], "little", signed=True),
                "elevation_deg": int.from_bytes(payload[offset + 4 : offset + 5], "little", signed=True),
                "age": payload[offset + 5],
            }
        )
    return {
        "payload_length": len(payload),
        "itow_ms": int.from_bytes(payload[0:4], "little"),
        "week": int.from_bytes(payload[4:6], "little", signed=True),
        "num_visible_sats": payload[6],
        "num_svs": num_svs,
        "parsed_sats": len(satellites),
        "satellites": satellites,
    }


def parse_nav_status(payload: bytes) -> dict[str, Any]:
    if len(payload) < 16:
        return {"payload_length": len(payload), "parse_error": "payload shorter than NAV-STATUS minimum"}
    return {
        "itow_ms": int.from_bytes(payload[0:4], "little"),
        "gps_fix": payload[4],
        "flags": payload[5],
        "fix_status": payload[6],
        "flags2": payload[7],
        "ttff_ms": int.from_bytes(payload[8:12], "little"),
        "time_to_first_fix_ms": int.from_bytes(payload[12:16], "little"),
    }


def parse_nav_sol(payload: bytes) -> dict[str, Any]:
    if len(payload) < 52:
        return {"payload_length": len(payload), "parse_error": "payload shorter than NAV-SOL minimum"}
    return {
        "itow_ms": int.from_bytes(payload[0:4], "little"),
        "gps_fix": payload[10],
        "flags": payload[11],
        "ecef_x_cm": int.from_bytes(payload[12:16], "little", signed=True),
        "ecef_y_cm": int.from_bytes(payload[16:20], "little", signed=True),
        "ecef_z_cm": int.from_bytes(payload[20:24], "little", signed=True),
        "position_accuracy_cm": int.from_bytes(payload[24:28], "little"),
        "speed_accuracy_cm_s": int.from_bytes(payload[44:48], "little"),
        "position_dop": int.from_bytes(payload[48:50], "little") / 100.0,
        "satellites_used": payload[50],
    }


def parse_ack(payload: bytes, *, acknowledged: bool) -> dict[str, Any]:
    if len(payload) < 2:
        return {"payload_length": len(payload), "parse_error": "payload shorter than ACK payload"}
    msg_class = payload[0]
    msg_id = payload[1]
    target_key = UBX_RESPONSE_KEYS.get((msg_class, msg_id))
    for name, poll in UBX_POLLS.items():
        if poll == (msg_class, msg_id):
            target_key = name
            break
    return {
        "payload_length": len(payload),
        "acknowledged": acknowledged,
        "target_class": msg_class,
        "target_id": msg_id,
        "target_key": target_key or f"0x{msg_class:02x}:0x{msg_id:02x}",
    }


def parse_nmea_gsv(raw_text: str) -> dict[str, Any]:
    records = []
    total_visible_values = []
    lines = list(_iter_nmea_sentences(raw_text))
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("$") or "GSV" not in stripped[:8]:
            continue
        body = stripped[1:].split("*", 1)[0]
        fields = body.split(",")
        if len(fields) < 4 or fields[0][-3:] != "GSV":
            continue
        total_visible = _safe_int(fields[3])
        if total_visible is not None:
            total_visible_values.append(total_visible)
        for offset in range(4, len(fields), 4):
            if len(fields) < offset + 4:
                break
            svid = _safe_int(fields[offset])
            if svid is None:
                continue
            records.append(
                {
                    "talker": fields[0][:-3],
                    "svid": svid,
                    "elevation_deg": _safe_int(fields[offset + 1]),
                    "azimuth_deg": _safe_int(fields[offset + 2]),
                    "cno_dbhz": _safe_int(fields[offset + 3]),
                }
            )
    cno_values = [record["cno_dbhz"] for record in records if record["cno_dbhz"] is not None]
    return {
        "sentence_count": sum(1 for line in lines if line.strip().startswith("$") and "GSV" in line[:8]),
        "reported_visible_satellites": max(total_visible_values) if total_visible_values else None,
        "parsed_satellites": len(records),
        "nonzero_cno_count": sum(1 for value in cno_values if value > 0),
        "max_cno_dbhz": max(cno_values) if cno_values else None,
        "satellites": records,
    }


def parse_nmea_pubx(raw_text: str) -> dict[str, Any]:
    lines = []
    by_message: dict[str, int] = {}
    pubx03_satellite_lines = []
    for line in _iter_nmea_sentences(raw_text):
        stripped = line.strip()
        if not stripped.startswith("$PUBX,"):
            continue
        body = stripped[1:].split("*", 1)[0]
        fields = body.split(",")
        message_id = fields[1] if len(fields) > 1 else ""
        by_message[message_id] = by_message.get(message_id, 0) + 1
        lines.append(stripped)
        if message_id == "03":
            pubx03_satellite_lines.append(stripped)
    return {
        "sentence_count": len(lines),
        "by_message": by_message,
        "pubx00_seen": by_message.get("00", 0) > 0,
        "pubx03_seen": by_message.get("03", 0) > 0,
        "pubx03_sentence_count": len(pubx03_satellite_lines),
        "lines_sample": lines[:10],
    }


def parse_nmea_txt(raw_text: str) -> dict[str, Any]:
    messages = []
    for line in _iter_nmea_sentences(raw_text):
        stripped = line.strip()
        if not stripped.startswith("$") or "TXT" not in stripped[:8]:
            continue
        body = stripped[1:].split("*", 1)[0]
        fields = body.split(",")
        if len(fields) > 4:
            messages.append(",".join(fields[4:]).strip())
    joined = " ".join(messages).upper()
    if "ANTENNA OK" in joined:
        antenna_text_status = "OK"
    elif "ANTENNA SHORT" in joined:
        antenna_text_status = "SHORT"
    elif "ANTENNA OPEN" in joined:
        antenna_text_status = "OPEN"
    elif "ANTENNA" in joined:
        antenna_text_status = "UNKNOWN"
    else:
        antenna_text_status = None
    return {
        "sentence_count": len(messages),
        "messages": messages[:20],
        "antenna_text_status": antenna_text_status,
    }


def _iter_nmea_sentences(raw_text: str) -> list[str]:
    sentences: list[str] = []
    for part in raw_text.replace("\r", "\n").split("\n"):
        start = part.find("$")
        while start >= 0:
            next_start = part.find("$", start + 1)
            sentence = part[start : next_start if next_start >= 0 else len(part)].strip()
            if sentence:
                sentences.append(sentence)
            start = next_start
    return sentences


def read_serial_debug_bytes(
    *,
    port: str,
    baud: int,
    duration_seconds: float,
    poll_gap_seconds: float,
    send_pubx_probe: bool = True,
) -> bytes:
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

        if send_pubx_probe:
            for poll in PUBX_POLLS:
                os.write(fd, poll)
                time.sleep(poll_gap_seconds)

        for name in ("MON-VER", "CFG-ANT", "MON-HW", "NAV-SVINFO", "RXM-SVSI", "NAV-STATUS", "NAV-SOL"):
            os.write(fd, build_ubx_poll(*UBX_POLLS[name]))
            time.sleep(poll_gap_seconds)

        chunks: list[bytes] = []
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            timeout = max(0.0, min(0.2, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                continue
            chunk = os.read(fd, 1024)
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def build_debug_payload(*, data: bytes, device_port: str, baud: int) -> dict[str, Any]:
    frames = parse_ubx_frames(data)
    frame_payloads: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        parsed = parse_known_frame(frame)
        frame_payloads.setdefault(frame.key, []).append(
            {
                "checksum_valid": frame.checksum_valid,
                "payload_length": len(frame.payload),
                "parsed": parsed,
                "raw_hex": frame.raw_bytes.hex(),
            }
        )

    raw_text = data.decode("ascii", errors="ignore")
    nmea_gsv = parse_nmea_gsv(raw_text)
    nmea_pubx = parse_nmea_pubx(raw_text)
    nmea_txt = parse_nmea_txt(raw_text)
    summary = summarize_observation(
        frame_payloads=frame_payloads,
        nmea_gsv=nmea_gsv,
        nmea_pubx=nmea_pubx,
        nmea_txt=nmea_txt,
    )
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_ublox5_gnss_debug",
        "hardware_kind": "ublox5_gnss_diagnostic_poll",
        "device_port": device_port,
        "baud": baud,
        "ubx_frame_count": len(frames),
        "ubx_supported_observed": bool(frames),
        "ubx_frames": frame_payloads,
        "nmea_gsv": nmea_gsv,
        "nmea_pubx": nmea_pubx,
        "nmea_txt": nmea_txt,
        "summary": summary,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_poll_only",
    }


def parse_known_frame(frame: UbxFrame) -> dict[str, Any]:
    if frame.key == "MON-VER":
        return parse_mon_ver(frame.payload)
    if frame.key == "CFG-ANT":
        return parse_cfg_ant(frame.payload)
    if frame.key == "MON-HW":
        return parse_mon_hw(frame.payload)
    if frame.key == "NAV-SVINFO":
        return parse_nav_svinfo(frame.payload)
    if frame.key == "RXM-SVSI":
        return parse_rxm_svsi(frame.payload)
    if frame.key == "NAV-STATUS":
        return parse_nav_status(frame.payload)
    if frame.key == "NAV-SOL":
        return parse_nav_sol(frame.payload)
    if frame.key == "ACK-NAK":
        return parse_ack(frame.payload, acknowledged=False)
    if frame.key == "ACK-ACK":
        return parse_ack(frame.payload, acknowledged=True)
    return {}


def summarize_observation(
    *,
    frame_payloads: dict[str, list[dict[str, Any]]],
    nmea_gsv: dict[str, Any],
    nmea_pubx: dict[str, Any],
    nmea_txt: dict[str, Any],
) -> dict[str, Any]:
    cfg_ant = _latest_parsed(frame_payloads, "CFG-ANT")
    mon_hw = _latest_parsed(frame_payloads, "MON-HW")
    nav_svinfo = _latest_parsed(frame_payloads, "NAV-SVINFO")
    rxm_svsi = _latest_parsed(frame_payloads, "RXM-SVSI")
    ack_nak_count = len(frame_payloads.get("ACK-NAK") or [])
    ack_ack_count = len(frame_payloads.get("ACK-ACK") or [])
    max_cno_values = [
        value
        for value in (nmea_gsv.get("max_cno_dbhz"), nav_svinfo.get("max_cno_dbhz"))
        if isinstance(value, (int, float))
    ]
    max_cno = max(max_cno_values) if max_cno_values else None
    nonzero_cno = int(nmea_gsv.get("nonzero_cno_count") or 0) + int(nav_svinfo.get("nonzero_cno_count") or 0)

    antenna_label = mon_hw.get("antenna_status_label")
    if antenna_label == "SHORT":
        likely_state = "antenna_bias_short"
    elif antenna_label == "OPEN":
        likely_state = "antenna_open_or_not_connected"
    elif nonzero_cno == 0 and max_cno in (None, 0):
        likely_state = "no_rf_signal_observed"
    elif max_cno is not None and max_cno < 20:
        likely_state = "rf_signal_very_weak"
    elif max_cno is not None and max_cno < 30:
        likely_state = "rf_signal_weak"
    elif max_cno is not None:
        likely_state = "rf_signal_observed"
    else:
        likely_state = "insufficient_signal_evidence"

    if nmea_pubx.get("pubx00_seen") or nmea_pubx.get("pubx03_seen") or ack_nak_count or ack_ack_count:
        command_path_state = "receiver_response_observed"
    elif nmea_gsv.get("sentence_count"):
        command_path_state = "host_rx_only_observed"
    else:
        command_path_state = "no_stream_or_command_response"

    return {
        "antenna_status_label": antenna_label,
        "antenna_power_label": mon_hw.get("antenna_power_label"),
        "antenna_config_flags_decoded": cfg_ant.get("flags_decoded"),
        "antenna_text_status": nmea_txt.get("antenna_text_status"),
        "noise_per_ms": mon_hw.get("noise_per_ms"),
        "agc_count": mon_hw.get("agc_count"),
        "max_cno_dbhz": max_cno,
        "nonzero_cno_count": nonzero_cno,
        "likely_state": likely_state,
        "command_path_state": command_path_state,
        "pubx00_seen": bool(nmea_pubx.get("pubx00_seen")),
        "pubx03_seen": bool(nmea_pubx.get("pubx03_seen")),
        "ubx_ack_nak_count": ack_nak_count,
        "ubx_ack_ack_count": ack_ack_count,
        "rxm_svsi_num_visible_sats": rxm_svsi.get("num_visible_sats"),
        "ubx_mon_hw_seen": bool(mon_hw),
        "ubx_nav_svinfo_seen": bool(nav_svinfo),
        "ubx_cfg_ant_seen": bool(cfg_ant),
        "ubx_rxm_svsi_seen": bool(rxm_svsi),
    }


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _latest_parsed(frame_payloads: dict[str, list[dict[str, Any]]], key: str) -> dict[str, Any]:
    frames = frame_payloads.get(key) or []
    if not frames:
        return {}
    parsed = frames[-1].get("parsed")
    return parsed if isinstance(parsed, dict) else {}


def _cstring(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _safe_int(value: str) -> int | None:
    try:
        if value == "":
            return None
        return int(value)
    except ValueError:
        return None


def _termios_baud_constant(baud: int) -> int:
    constant_name = f"B{baud}"
    if not hasattr(termios, constant_name):
        raise RuntimeError(f"unsupported serial baud rate for stdlib fallback: {baud}")
    return getattr(termios, constant_name)


def _raw_hex_to_bytes(raw_hex: str) -> bytes:
    compact = raw_hex.replace("0x", "").replace(" ", "").replace("\n", "").replace(":", "")
    return bytes.fromhex(compact)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll u-blox 5 GNSS hardware and RF signal diagnostics.")
    parser.add_argument("--port", default="/dev/ttyAMA0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--duration-seconds", type=float, default=3.0)
    parser.add_argument("--poll-gap-seconds", type=float, default=0.12)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--raw-hex", help="Parse captured bytes from hex instead of opening serial.")
    parser.add_argument("--raw-text", help="Parse captured text instead of opening serial.")
    parser.add_argument("--no-pubx-probe", action="store_true", help="Do not send PUBX,00/PUBX,03 NMEA polls.")
    args = parser.parse_args(argv)

    try:
        if args.raw_hex is not None:
            data = _raw_hex_to_bytes(args.raw_hex)
        elif args.raw_text is not None:
            data = args.raw_text.encode("ascii", errors="replace")
        else:
            data = read_serial_debug_bytes(
                port=args.port,
                baud=args.baud,
                duration_seconds=args.duration_seconds,
                poll_gap_seconds=args.poll_gap_seconds,
                send_pubx_probe=not args.no_pubx_probe,
            )
        payload = build_debug_payload(data=data, device_port=args.port, baud=args.baud)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    append_jsonl(payload, args.output_jsonl)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
