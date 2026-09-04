#!/usr/bin/env python3
"""Send a bounded old-PC debug report to Scout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scout.hardware.old_pc_debug_link import (  # noqa: E402
    build_simulated_old_pc_report,
    collect_current_host_debug_report,
    post_old_pc_debug_report,
)

DEFAULT_INGEST_URL = "http://10.55.0.1:8765/hardware/old-pc-debug/reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect a read-only old-PC debug report and send it to Scout."
    )
    parser.add_argument(
        "--ingest-url",
        default=DEFAULT_INGEST_URL,
        help="Scout old-PC debug ingest URL.",
    )
    parser.add_argument(
        "--subject-ref",
        default="old-pc-candidate",
        help="Non-secret label for the old PC candidate.",
    )
    parser.add_argument(
        "--transport",
        choices=("usb_gadget_ethernet", "loopback_smoke", "manual_file"),
        default="usb_gadget_ethernet",
        help="Local link used to reach Scout.",
    )
    parser.add_argument(
        "--simulate-old-pc",
        action="store_true",
        help="Send the deterministic no-RJ45/no-display fixture for Mac loopback smoke.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
        help="HTTP timeout for the local Scout ingest call.",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Print the report without posting it.",
    )
    parser.add_argument(
        "--output-report-json",
        default=None,
        help="Optional path to write the report before sending.",
    )
    args = parser.parse_args(argv)

    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    transport = args.transport
    if args.simulate_old_pc:
        report = build_simulated_old_pc_report(
            subject_ref=args.subject_ref,
            transport=transport,
        )
    else:
        report = collect_current_host_debug_report(
            subject_ref=args.subject_ref,
            transport=transport,
        )

    report_payload = report.model_dump(mode="json")
    if args.output_report_json:
        report_path = Path(args.output_report_json).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.no_send:
        print(json.dumps(report_payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    receipt = post_old_pc_debug_report(
        report,
        ingest_url=args.ingest_url,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
