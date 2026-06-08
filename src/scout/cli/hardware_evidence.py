"""CLI for producing Scout AI OS hardware evidence JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scout.hardware.evidence import (
    build_hardware_evidence,
    build_hardware_evidence_directory,
    load_host_probe_samples,
    load_hardware_evidence_samples,
    load_nmea_samples,
    load_sensor_logger_csv_samples,
    load_sensor_logger_json_samples,
    write_hardware_evidence,
    write_hardware_evidence_directory,
)

SOURCE_LOADERS = {
    "sample-json": load_hardware_evidence_samples,
    "sensor-logger-json": load_sensor_logger_json_samples,
    "sensor-logger-csv": load_sensor_logger_csv_samples,
    "nmea": load_nmea_samples,
    "host-probe-json": load_host_probe_samples,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build boundary-tagged hardware/mobile evidence JSON."
    )
    parser.add_argument("--source", required=True, help="Evidence source label.")
    parser.add_argument(
        "--source-device-id",
        default=None,
        help="Optional source device identifier; do not put secrets here.",
    )
    parser.add_argument(
        "--sample-json",
        required=False,
        help="Path to one sample JSON object, a sample list, or an object with samples.",
    )
    parser.add_argument(
        "--source-format",
        choices=sorted(SOURCE_LOADERS),
        default="sample-json",
        help="Input format to convert into Scout hardware evidence samples.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output JSON path, or '-' for stdout.",
    )
    parser.add_argument(
        "--evidence-dir",
        default=None,
        help=(
            "Optional directory that receives the evidence JSON and "
            "evidence-directory.json index."
        ),
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Optional non-secret note to attach. May be repeated.",
    )
    args = parser.parse_args(argv)
    if not args.sample_json:
        parser.error("--sample-json is required for the selected source format")

    samples = SOURCE_LOADERS[args.source_format](Path(args.sample_json))

    artifact = build_hardware_evidence(
        source=args.source,
        source_device_id=args.source_device_id,
        samples=samples,
        notes=args.note,
    )
    output_path: Path | None
    if args.evidence_dir and args.output == "-":
        evidence_dir = Path(args.evidence_dir)
        output_path = evidence_dir / f"{artifact.artifact_id}.json"
    elif args.output == "-":
        output_path = None
    else:
        output_path = Path(args.output)

    if output_path is None:
        print(json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        write_hardware_evidence(artifact, output_path)
        if args.evidence_dir:
            evidence_dir = Path(args.evidence_dir)
            directory = build_hardware_evidence_directory(
                root=evidence_dir,
                artifacts=[(artifact, output_path)],
                notes=["directory index is advisory-only and not runtime truth"],
            )
            write_hardware_evidence_directory(
                directory,
                evidence_dir / "evidence-directory.json",
            )
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
