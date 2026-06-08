"""CLI for producing Scout AI OS hardware evidence JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scout.hardware.evidence import (
    build_hardware_evidence,
    load_hardware_evidence_samples,
    write_hardware_evidence,
)


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
        required=True,
        help="Path to one sample JSON object, a sample list, or an object with samples.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output JSON path, or '-' for stdout.",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Optional non-secret note to attach. May be repeated.",
    )
    args = parser.parse_args(argv)

    artifact = build_hardware_evidence(
        source=args.source,
        source_device_id=args.source_device_id,
        samples=load_hardware_evidence_samples(Path(args.sample_json)),
        notes=args.note,
    )
    if args.output == "-":
        print(json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        write_hardware_evidence(artifact, Path(args.output))
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
