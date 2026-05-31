from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_sensorlog_replay import run_sensorlog_replays, write_estimates_jsonl  # noqa: E402
from tools.ins_dr_trajectory_compare_map import build_trajectory_comparison  # noqa: E402


@dataclass(frozen=True)
class MethodConfig:
    name: str
    pdr_profile: str
    deployability: str
    interpretation: str
    pdr_resolution_mode: str | None = None
    pdr_heading_policy: str | None = None


DEFAULT_METHODS = (
    MethodConfig(
        name="baseline_sparse_course",
        pdr_profile="manual",
        pdr_resolution_mode="pedometer_updates",
        pdr_heading_policy="sensorlog_course",
        deployability="diagnostic_baseline_not_recommended_for_wearable_clients",
        interpretation="Sparse pedometer updates plus direct SensorLog course; useful only as the legacy baseline.",
    ),
    MethodConfig(
        name="distributed_sensorlog_course",
        pdr_profile="manual",
        pdr_resolution_mode="distributed_sensorlog",
        pdr_heading_policy="sensorlog_course",
        deployability="diagnostic_not_recommended_for_wearable_clients",
        interpretation="Higher cadence, but still trusts noisy watch/GPS course as heading.",
    ),
    MethodConfig(
        name="distributed_reliable_course",
        pdr_profile="wearable_course_gated",
        deployability="diagnostic_candidate",
        interpretation="Keeps course-over-ground only when accuracy and speed gates pass.",
    ),
    MethodConfig(
        name="wearable_route_constrained",
        pdr_profile="wearable_route_constrained",
        deployability="recommended_wearable_default",
        interpretation="Wearable-first default: use pedometer distance at SensorLog cadence and do not use uncalibrated watch heading.",
    ),
    MethodConfig(
        name="route_heading_oracle",
        pdr_profile="route_heading_oracle",
        deployability="upper_bound_not_independent_sensor_evidence",
        interpretation="Upper-bound replay that uses the planned route heading; not a standalone wearable sensor proof.",
    ),
)


def build_sensorlog_method_matrix(
    *,
    sensorlog_paths: list[Path],
    output_dir: Path,
    overpass_geojson_path: Path | None = None,
    method_names: list[str] | None = None,
    max_horizontal_accuracy_m: float = 25.0,
    gnss_anchor_interval_s: float = 60.0,
    max_dead_reckoning_seconds: float = 300.0,
    max_dead_reckoning_distance_m: float = 250.0,
    reliable_course_min_speed_mps: float = 0.5,
    max_interpolation_gap_s: float = 10.0,
    top_error_count: int = 20,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_methods = _select_methods(method_names)
    method_summaries = []

    for method in selected_methods:
        method_dir = output_dir / method.name
        replay_dir = method_dir / "replay"
        compare_dir = method_dir / "compare"
        replay_dir.mkdir(parents=True, exist_ok=True)
        replay_report_path = replay_dir / "report.json"
        estimates_jsonl_path = replay_dir / "estimates.jsonl"

        replay_report = run_sensorlog_replays(
            input_paths=[path.expanduser().resolve() for path in sensorlog_paths],
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
            gnss_anchor_interval_s=gnss_anchor_interval_s,
            max_dead_reckoning_seconds=max_dead_reckoning_seconds,
            max_dead_reckoning_distance_m=max_dead_reckoning_distance_m,
            pdr_profile=method.pdr_profile,
            pdr_resolution_mode=method.pdr_resolution_mode,
            pdr_heading_policy=method.pdr_heading_policy,
            reliable_course_min_speed_mps=reliable_course_min_speed_mps,
            include_estimates=True,
        )
        write_estimates_jsonl(replay_report, estimates_jsonl_path)
        replay_report_path.write_text(
            json.dumps(_without_embedded_estimates(replay_report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        compare_report = build_trajectory_comparison(
            sensorlog_paths=[path.expanduser().resolve() for path in sensorlog_paths],
            estimates_jsonl_path=estimates_jsonl_path,
            overpass_geojson_path=overpass_geojson_path.expanduser().resolve() if overpass_geojson_path else None,
            output_dir=compare_dir,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
            max_interpolation_gap_s=max_interpolation_gap_s,
            top_error_count=top_error_count,
        )
        method_summaries.append(
            _method_summary(
                method=method,
                replay_report=replay_report,
                compare_report=compare_report,
                replay_report_path=replay_report_path,
                estimates_jsonl_path=estimates_jsonl_path,
            )
        )

    summary = {
        "artifact_kind": "scout_ins_dr_sensorlog_method_matrix",
        "source_tool": "ins_dr_sensorlog_method_matrix",
        "sensorlog_paths": [str(path.expanduser().resolve()) for path in sensorlog_paths],
        "overpass_geojson_path": str(overpass_geojson_path.expanduser().resolve()) if overpass_geojson_path else None,
        "method_count": len(method_summaries),
        "max_horizontal_accuracy_m": max_horizontal_accuracy_m,
        "gnss_anchor_interval_s": gnss_anchor_interval_s,
        "wearable_first_assumption": {
            "expected_client_fraction": ">=90%",
            "required_client_source": "watch_or_wearable_pdr_imu",
            "scout_host_imu_required_for_default_client": False,
            "scout_host_imu_role": "optional higher-fidelity local baseline, calibration, and vehicle/body-mounted enhancement",
        },
        "recommended_default_method": "wearable_route_constrained",
        "recommended_default_reason": (
            "It is the best deployable wearable-safe profile in this matrix because it improves cadence with "
            "pedometerDistance while avoiding uncalibrated watch heading and low-speed course-over-ground flips."
        ),
        "best_observed_method_by_median_dr_error": _best_method_by_median_error(method_summaries),
        "methods": method_summaries,
        "does_not_validate": [
            "live raw GNSS NMEA reception on Scout",
            "live wheel encoder odometry",
            "live Hiwonder raw IMU heading baseline",
            "Phase 1 live safety decision mutation",
        ],
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_sensorlog_method_matrix_only",
        "live_navigation_completion_proof": False,
    }

    summary_path = output_dir / "method_matrix_summary.json"
    markdown_path = output_dir / "method_matrix_summary.md"
    summary["outputs"] = {
        "summary_json": str(summary_path),
        "summary_markdown": str(markdown_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown_summary(summary), encoding="utf-8")
    return summary


def _select_methods(method_names: list[str] | None) -> list[MethodConfig]:
    by_name = {method.name: method for method in DEFAULT_METHODS}
    if not method_names:
        return list(DEFAULT_METHODS)
    missing = [name for name in method_names if name not in by_name]
    if missing:
        raise ValueError(f"Unsupported method name(s): {', '.join(missing)}")
    return [by_name[name] for name in method_names]


def _method_summary(
    *,
    method: MethodConfig,
    replay_report: dict[str, Any],
    compare_report: dict[str, Any],
    replay_report_path: Path,
    estimates_jsonl_path: Path,
) -> dict[str, Any]:
    reason_counts = _degradation_reason_counts(replay_report)
    no_good_gps_count = sum(item["no_good_gps_summary"]["no_good_gps_count"] for item in compare_report["reports"])
    pdr_on_no_good_gps_count = sum(
        item["no_good_gps_summary"]["pdr_on_no_good_gps_count"] for item in compare_report["reports"]
    )
    imu_on_no_good_gps_count = sum(
        item["no_good_gps_summary"]["imu_on_no_good_gps_count"] for item in compare_report["reports"]
    )
    dr_error = compare_report["bundle_summary"]["dead_reckoning_error_m"]
    return {
        "name": method.name,
        "pdr_profile": replay_report["pdr_profile"],
        "pdr_profile_notes": replay_report["pdr_profile_notes"],
        "pdr_resolution_mode": replay_report["pdr_resolution_mode"],
        "pdr_heading_policy": replay_report["pdr_heading_policy"],
        "deployability": method.deployability,
        "interpretation": method.interpretation,
        "recommended_for_wearable_clients": method.name == "wearable_route_constrained",
        "z_shape_risk": _z_shape_risk(reason_counts),
        "degradation_reason_counts": dict(reason_counts),
        "replay_bundle_summary": replay_report["bundle_summary"],
        "trajectory_bundle_summary": compare_report["bundle_summary"],
        "weak_or_no_good_gps": {
            "sample_count": no_good_gps_count,
            "pdr_sample_count": pdr_on_no_good_gps_count,
            "imu_sample_count": imu_on_no_good_gps_count,
        },
        "dr_error_m": {
            "count": dr_error["count"],
            "median": dr_error["median"],
            "mean": dr_error["mean"],
            "p95": dr_error["p95"],
            "max": dr_error["max"],
        },
        "per_file": _per_file_summary(compare_report),
        "outputs": {
            "replay_report_json": str(replay_report_path),
            "estimates_jsonl": str(estimates_jsonl_path),
            **compare_report["outputs"],
        },
        "live_navigation_completion_proof": False,
    }


def _degradation_reason_counts(replay_report: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for report in replay_report.get("reports", []):
        for estimate in report.get("estimates", []):
            reasons = estimate.get("degradation_reasons") or []
            if not reasons:
                counts["no_reason"] += 1
            for reason in reasons:
                counts[str(reason)] += 1
    return counts


def _z_shape_risk(reason_counts: Counter[str]) -> str:
    reverse = reason_counts.get("heading_opposes_route", 0)
    disagreement = reason_counts.get("heading_route_disagreement", 0)
    if reverse > 0:
        return "high_reverse_heading_observed"
    if disagreement > 0:
        return "medium_heading_disagreement_observed"
    return "low_no_reverse_heading_evidence"


def _per_file_summary(compare_report: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for item in compare_report["reports"]:
        no_good = item["no_good_gps_summary"]
        dr = item["dead_reckoning_error_m"]
        summaries.append(
            {
                "input_path": item["input_path"],
                "gps_sample_count": item["gps_sample_count"],
                "dead_reckoning_sample_count": item["dead_reckoning_sample_count"],
                "no_good_gps_count": no_good["no_good_gps_count"],
                "pdr_on_no_good_gps_count": no_good["pdr_on_no_good_gps_count"],
                "imu_on_no_good_gps_count": no_good["imu_on_no_good_gps_count"],
                "dr_error_m": {
                    "count": dr["count"],
                    "median": dr["median"],
                    "mean": dr["mean"],
                    "p95": dr["p95"],
                    "max": dr["max"],
                },
            }
        )
    return summaries


def _best_method_by_median_error(methods: list[dict[str, Any]]) -> str | None:
    with_errors = [
        method for method in methods if isinstance(method["dr_error_m"].get("median"), (int, float))
    ]
    if not with_errors:
        return None
    return min(with_errors, key=lambda method: method["dr_error_m"]["median"])["name"]


def _without_embedded_estimates(report: dict[str, Any]) -> dict[str, Any]:
    copied = {**report}
    copied["reports"] = []
    for item in report.get("reports", []):
        stripped = {**item}
        stripped.pop("estimates", None)
        copied["reports"].append(stripped)
    return copied


def _markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Scout INS/DR SensorLog Method Matrix",
        "",
        f"Recommended default: `{summary['recommended_default_method']}`.",
        "",
        summary["recommended_default_reason"],
        "",
        "| Method | Deployability | Profile | Resolution | Heading | DR median | DR mean | DR p95 | DR count | Z-risk | Weak GPS + PDR |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for method in summary["methods"]:
        dr = method["dr_error_m"]
        weak = method["weak_or_no_good_gps"]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{method['name']}`",
                    method["deployability"],
                    f"`{method['pdr_profile']}`",
                    f"`{method['pdr_resolution_mode']}`",
                    f"`{method['pdr_heading_policy']}`",
                    _fmt_m(dr["median"]),
                    _fmt_m(dr["mean"]),
                    _fmt_m(dr["p95"]),
                    str(dr["count"]),
                    method["z_shape_risk"],
                    str(weak["pdr_sample_count"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is offline Apple Watch/SensorLog replay evidence.",
            "- It does not prove live Scout raw GNSS, wheel odometry, Hiwonder raw IMU, or Phase 1 safety mutation.",
            "- `route_heading_oracle` is an upper-bound diagnostic, not independent wearable sensor evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _fmt_m(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:.2f} m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Scout INS/DR SensorLog replay methods and compare each trajectory against GPS."
    )
    parser.add_argument("--input", type=Path, action="append", required=True, help="SensorLog JSON input. May repeat.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overpass-geojson", type=Path, help="Optional Overpass GeoJSON context.")
    parser.add_argument(
        "--method",
        action="append",
        choices=[method.name for method in DEFAULT_METHODS],
        help="Method to run. May repeat. Defaults to the full matrix.",
    )
    parser.add_argument("--max-horizontal-accuracy-m", type=float, default=25.0)
    parser.add_argument("--gnss-anchor-interval-s", type=float, default=60.0)
    parser.add_argument("--max-dead-reckoning-seconds", type=float, default=300.0)
    parser.add_argument("--max-dead-reckoning-distance-m", type=float, default=250.0)
    parser.add_argument("--reliable-course-min-speed-mps", type=float, default=0.5)
    parser.add_argument("--max-interpolation-gap-s", type=float, default=10.0)
    parser.add_argument("--top-error-count", type=int, default=20)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = build_sensorlog_method_matrix(
            sensorlog_paths=args.input,
            output_dir=args.output_dir,
            overpass_geojson_path=args.overpass_geojson,
            method_names=args.method,
            max_horizontal_accuracy_m=args.max_horizontal_accuracy_m,
            gnss_anchor_interval_s=args.gnss_anchor_interval_s,
            max_dead_reckoning_seconds=args.max_dead_reckoning_seconds,
            max_dead_reckoning_distance_m=args.max_dead_reckoning_distance_m,
            reliable_course_min_speed_mps=args.reliable_course_min_speed_mps,
            max_interpolation_gap_s=args.max_interpolation_gap_s,
            top_error_count=args.top_error_count,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
