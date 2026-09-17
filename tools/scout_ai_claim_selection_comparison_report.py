#!/usr/bin/env python3
"""Verify a completed fixed-case comparison without invoking a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scout.nextgen.claim_comparison_report import build_comparison_report
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--egress-dir", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_comparison_report(
        baseline_dir=args.baseline_dir, result_dir=args.result_dir, egress_dir=args.egress_dir,
        config=OpenAICompatibleBackendConfig.from_json_file(args.runtime_config),
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report))
    return 0 if report["comparison_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
