#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GPX_NS = "http://www.topografix.com/GPX/1/1"
SCOUT_NS = "https://scout-fusion.local/gpx/extensions/1"

ET.register_namespace("", GPX_NS)
ET.register_namespace("scout", SCOUT_NS)


def _to_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _iso_time(record: dict[str, Any]) -> str | None:
    raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
    if isinstance(raw, str) and raw and raw != "null":
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return raw

    ts = _to_float(record.get("locationTimestamp_since1970"))
    if ts is not None and ts > 0:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _sanitize_extension_name(key: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    if not cleaned or not re.match(r"[A-Za-z_]", cleaned[0]):
        cleaned = f"field_{cleaned}"
    return cleaned


def _add_text(parent: ET.Element, tag: str, value: Any) -> None:
    if value in (None, "", "null"):
        return
    child = ET.SubElement(parent, tag)
    child.text = str(value)


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        imu_data = payload.get("imu_data")
        if isinstance(imu_data, list):
            return [item for item in imu_data if isinstance(item, dict)]
        return [payload]
    raise ValueError("SensorLog JSON must be a list, dict, or dict with imu_data list")


def _valid_location(record: dict[str, Any], max_horizontal_accuracy: float | None) -> tuple[float, float] | None:
    lat = _to_float(record.get("locationLatitude"))
    lon = _to_float(record.get("locationLongitude"))
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    accuracy = _to_float(record.get("locationHorizontalAccuracy"))
    if max_horizontal_accuracy is not None and accuracy is not None and accuracy > max_horizontal_accuracy:
        return None
    return lat, lon


def sensorlog_json_to_gpx(
    input_path: Path,
    output_path: Path,
    *,
    track_name: str | None = None,
    max_horizontal_accuracy: float | None = None,
) -> int:
    payload = json.loads(input_path.read_text())
    records = _records_from_payload(payload)
    if not track_name:
        track_name = input_path.stem

    gpx = ET.Element(
        f"{{{GPX_NS}}}gpx",
        {
            "version": "1.1",
            "creator": "S.C.O.U.T. Fusion sensorlog_to_gpx.py",
        },
    )
    metadata = ET.SubElement(gpx, f"{{{GPX_NS}}}metadata")
    _add_text(metadata, f"{{{GPX_NS}}}name", track_name)
    trk = ET.SubElement(gpx, f"{{{GPX_NS}}}trk")
    _add_text(trk, f"{{{GPX_NS}}}name", track_name)
    trkseg = ET.SubElement(trk, f"{{{GPX_NS}}}trkseg")

    written = 0
    extension_fields = [
        "locationHorizontalAccuracy",
        "locationVerticalAccuracy",
        "locationSpeed",
        "locationCourse",
        "heartRateBPM",
        "heartRateBPS",
        "heartRateVariability",
        "pedometerDistance",
        "pedometerNumberOfSteps",
        "accelerometerAccelerationX",
        "accelerometerAccelerationY",
        "accelerometerAccelerationZ",
        "motionGravityX",
        "motionGravityY",
        "motionGravityZ",
        "motionUserAccelerationX",
        "motionUserAccelerationY",
        "motionUserAccelerationZ",
        "motionRotationRateX",
        "motionRotationRateY",
        "motionRotationRateZ",
        "motionYaw",
        "motionPitch",
        "motionRoll",
        "batteryLevel",
        "batteryState",
    ]

    for record in records:
        location = _valid_location(record, max_horizontal_accuracy)
        if location is None:
            continue

        lat, lon = location
        trkpt = ET.SubElement(
            trkseg,
            f"{{{GPX_NS}}}trkpt",
            {"lat": f"{lat:.8f}", "lon": f"{lon:.8f}"},
        )

        elevation = _to_float(record.get("locationAltitude"))
        if elevation is not None:
            _add_text(trkpt, f"{{{GPX_NS}}}ele", f"{elevation:.2f}")

        time_value = _iso_time(record)
        if time_value:
            _add_text(trkpt, f"{{{GPX_NS}}}time", time_value)

        extensions = ET.SubElement(trkpt, f"{{{GPX_NS}}}extensions")
        scout_sample = ET.SubElement(extensions, f"{{{SCOUT_NS}}}sample")
        for key in extension_fields:
            value = record.get(key)
            if value in (None, "", "null"):
                continue
            _add_text(scout_sample, f"{{{SCOUT_NS}}}{_sanitize_extension_name(key)}", value)

        written += 1

    if written == 0:
        raise ValueError("No valid GPS points found")

    tree = ET.ElementTree(gpx)
    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Apple Watch / SensorLog JSON into GPX.")
    parser.add_argument("input", type=Path, help="SensorLog JSON file")
    parser.add_argument("-o", "--output", type=Path, help="Output GPX path. Defaults to input basename with .gpx")
    parser.add_argument("--track-name", help="GPX track name")
    parser.add_argument(
        "--max-horizontal-accuracy",
        type=float,
        help="Drop points with locationHorizontalAccuracy above this many meters",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve() if args.output else input_path.with_suffix(".gpx")
    count = sensorlog_json_to_gpx(
        input_path,
        output_path,
        track_name=args.track_name,
        max_horizontal_accuracy=args.max_horizontal_accuracy,
    )
    print(f"Wrote {count} track points to {output_path}")


if __name__ == "__main__":
    main()
