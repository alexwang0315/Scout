#!/usr/bin/env python3
"""Compare two candidate-only TRH host executions within declared tolerances."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from terrain_route_host_parity import (  # noqa: E402
    TerrainRouteParityError,
    compare_terrain_route_hosts,
)


def _read_json(path: Path) -> dict:
    payload = json.loads(path.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TerrainRouteParityError(f"JSON input is not an object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two candidate-only Terrain Route Hypothesis executions. "
            "This checks model reproducibility, not trail existence or safety."
        )
    )
    parser.add_argument("--left-receipt", required=True, type=Path)
    parser.add_argument("--right-receipt", required=True, type=Path)
    parser.add_argument("--left-hypothesis", required=True, type=Path)
    parser.add_argument("--right-hypothesis", required=True, type=Path)
    parser.add_argument("--path-tolerance-m", type=float, default=0.1)
    parser.add_argument("--metric-abs-tolerance", type=float, default=1e-6)
    parser.add_argument("--corridor-relative-tolerance", type=float, default=0.03)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = compare_terrain_route_hosts(
            left_receipt=_read_json(args.left_receipt),
            right_receipt=_read_json(args.right_receipt),
            left_hypothesis=_read_json(args.left_hypothesis),
            right_hypothesis=_read_json(args.right_hypothesis),
            path_tolerance_m=args.path_tolerance_m,
            metric_abs_tolerance=args.metric_abs_tolerance,
            corridor_relative_tolerance=args.corridor_relative_tolerance,
        )
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError, TerrainRouteParityError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "scout_terrain_route_host_parity.v0_1",
                    "status": "unavailable",
                    "message": str(exc),
                    "authority": "candidate_only",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "safe_or_walkable": "not_determined",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] != "diverged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
