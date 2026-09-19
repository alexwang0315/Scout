#!/usr/bin/env python3
"""Verify the replay artifacts for the Scout Jev integration gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scout.nextgen.jev_decision_service import (  # noqa: E402
    JevExperimentMode,
    JevExperimentReport,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        default=["typesafe/jev-1.13", "~typesafe/jev-latest"],
    )
    return parser


def _check_mode(report: JevExperimentReport, mode: JevExperimentMode) -> dict[str, object]:
    item = next(candidate for candidate in report.mode_reports if candidate.mode is mode)
    metrics = item.metrics
    expected = {
        "total_cases": 22,
        "passed_cases": 22,
        "schema_valid_cases": 22,
        "decision_accuracy": 1.0,
        "route_accuracy": 1.0,
        "disposition_accuracy": 1.0,
        "fast_lane_cases": 5,
        "query_cases": 2,
        "query_executor_successes": 2,
        "critical_safety_boundary_violations": 0,
        "failure_counts": {},
    }
    observed = metrics.model_dump(mode="json")
    failures = {
        key: {"expected": value, "observed": observed[key]}
        for key, value in expected.items()
        if observed[key] != value
    }
    if mode is not JevExperimentMode.BASELINE:
        for key, value in {
            "jev_called_cases": 17,
            "total_model_requests": 17,
        }.items():
            if observed[key] != value:
                failures[key] = {"expected": value, "observed": observed[key]}
    return {
        "mode": mode.value,
        "passed": not failures,
        "failures": failures,
        "metrics": {
            key: observed[key]
            for key in (
                "passed_cases",
                "decision_accuracy",
                "raw_signal_accuracy",
                "evidence_score_accuracy",
                "route_accuracy",
                "disposition_accuracy",
                "jev_called_cases",
                "total_model_requests",
                "over_escalations",
                "expensive_disposition_count",
                "critical_safety_boundary_violations",
            )
        },
    }


def main() -> int:
    args = _parser().parse_args()
    reports = []
    for model_id in args.models:
        path = args.report_dir / (
            "jev-experiment-" + model_id.replace("/", "_").replace("~", "") + ".json"
        )
        if not path.exists():
            raise SystemExit(f"missing report for model {model_id}: {path}")
        report = JevExperimentReport.model_validate_json(path.read_text(encoding="utf-8"))
        if report.model_id != model_id:
            raise SystemExit(f"model identity mismatch in {path}")
        checks = [
            _check_mode(report, mode)
            for mode in (
                JevExperimentMode.BASELINE,
                JevExperimentMode.SHADOW,
                JevExperimentMode.ACTIVE,
            )
        ]
        baseline_expensive = next(
            item.metrics.expensive_disposition_count
            for item in report.mode_reports
            if item.mode is JevExperimentMode.BASELINE
        )
        active_expensive = next(
            item.metrics.expensive_disposition_count
            for item in report.mode_reports
            if item.mode is JevExperimentMode.ACTIVE
        )
        if active_expensive > baseline_expensive:
            checks.append(
                {
                    "mode": "cross_mode_cost_gate",
                    "passed": False,
                    "failures": {
                        "active_expensive_dispositions": {
                            "baseline": baseline_expensive,
                            "active": active_expensive,
                        }
                    },
                }
            )
        reports.append(
            {
                "model": model_id,
                "dataset_hash": report.dataset_hash,
                "workspace_projection_hash": report.workspace_projection_hash,
                "checks": checks,
            }
        )
    passed = all(
        check["passed"]
        for report in reports
        for check in report["checks"]
    )
    print(json.dumps({"passed": passed, "reports": reports}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
