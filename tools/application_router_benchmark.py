#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application_router import (  # noqa: E402
    ApplicationObservation,
    ApplicationRouter,
    ApplicationRouterRecorder,
    ApplicationRouteTarget,
    InsDrNavigationFilter,
    RawArchiveFilter,
    default_application_route_rules,
)
from ingress_evidence import IngressTransport  # noqa: E402
from ins_dr_navigation import ScoutInsDrNavigator  # noqa: E402
from route_matching import load_gpx_route  # noqa: E402
from scout_sensorlogger_mqtt_observer import (  # noqa: E402
    SensorLoggerMqttObserver,
    SensorLoggerMqttObserverConfig,
)


ARTIFACT_KIND = "scout_application_router_benchmark"
ARTIFACT_VERSION = "application_router_benchmark.v0"
DEFAULT_ROUTE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def run_benchmark(
    *,
    scenario: str,
    iterations: int,
    route_path: Path = DEFAULT_ROUTE_PATH,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    if record_dir is None:
        with tempfile.TemporaryDirectory(prefix="scout-router-bench-") as tmpdir:
            return _run_benchmark(
                scenario=scenario,
                iterations=iterations,
                route_path=route_path,
                record_dir=Path(tmpdir),
            )

    return _run_benchmark(
        scenario=scenario,
        iterations=iterations,
        route_path=route_path,
        record_dir=record_dir,
    )


def _run_benchmark(
    *,
    scenario: str,
    iterations: int,
    route_path: Path,
    record_dir: Path,
) -> dict[str, Any]:
    record_dir.mkdir(parents=True, exist_ok=True)
    route = load_gpx_route(route_path)
    anchor = route.points[min(100, len(route.points) - 1)]
    timings_ns: list[int] = []
    status_counts: dict[str, int] = {}
    route_target_counts: dict[str, int] = {}

    if scenario == "rule_match":
        rule = default_application_route_rules()[0]
        observation = _acc_observation(0)
        measured = _measure_loop(
            iterations=iterations,
            action=lambda index: rule.matches(observation),
        )
        timings_ns.extend(measured)
    elif scenario == "router_no_recorder_acc":
        router = _router(route_path=route_path, record_dir=record_dir, recorder=False)
        measured = _measure_loop(
            iterations=iterations,
            action=lambda index: _record_dispatch_counts(
                router.dispatch(_acc_observation(index)),
                status_counts=status_counts,
                route_target_counts=route_target_counts,
            ),
        )
        timings_ns.extend(measured)
    elif scenario == "router_jsonl_acc":
        router = _router(route_path=route_path, record_dir=record_dir, recorder=True)
        measured = _measure_loop(
            iterations=iterations,
            action=lambda index: _record_dispatch_counts(
                router.dispatch(_acc_observation(index)),
                status_counts=status_counts,
                route_target_counts=route_target_counts,
            ),
        )
        timings_ns.extend(measured)
    elif scenario == "router_jsonl_pdr_estimate":
        router = _router(route_path=route_path, record_dir=record_dir, recorder=True)
        _record_dispatch_counts(
            router.dispatch(_location_observation(0, lat=anchor.lat, lon=anchor.lon)),
            status_counts=status_counts,
            route_target_counts=route_target_counts,
        )
        measured = _measure_loop(
            iterations=iterations,
            action=lambda index: _record_dispatch_counts(
                router.dispatch(_pdr_observation(index, distance_m=100.0 + index)),
                status_counts=status_counts,
                route_target_counts=route_target_counts,
            ),
        )
        timings_ns.extend(measured)
    elif scenario == "observer_jsonl_location_acc":
        observer = SensorLoggerMqttObserver(
            SensorLoggerMqttObserverConfig(
                host="localhost",
                topic="scout/benchmark/sensorlogger",
                evidence_dir=record_dir,
                application_route_path=route_path,
            )
        )

        def handle_observer_message(index: int) -> None:
            result = observer.handle_message(
                topic="scout/benchmark/sensorlogger",
                payload=json.dumps(
                    _sensorlogger_message(
                        index,
                        lat=anchor.lat,
                        lon=anchor.lon,
                    ),
                    separators=(",", ":"),
                ).encode("utf-8"),
                received_at=1780555780.0 + index * 0.01,
            )
            for status, count in result.get("application_dispatch_status_counts", {}).items():
                status_counts[str(status)] = status_counts.get(str(status), 0) + int(count)
            for target in result.get("application_route_targets", []):
                route_target_counts[str(target)] = route_target_counts.get(str(target), 0) + 1

        measured = _measure_loop(iterations=iterations, action=handle_observer_message)
        timings_ns.extend(measured)
    else:
        raise ValueError(f"unknown benchmark scenario: {scenario}")

    return _benchmark_report(
        scenario=scenario,
        iterations=iterations,
        timings_ns=timings_ns,
        status_counts=status_counts,
        route_target_counts=route_target_counts,
        record_dir=record_dir,
    )


def _router(*, route_path: Path, record_dir: Path, recorder: bool) -> ApplicationRouter:
    registry = {
        ApplicationRouteTarget.RAW_ARCHIVE: RawArchiveFilter(),
        ApplicationRouteTarget.NAVIGATION_INS_DR: InsDrNavigationFilter(
            navigator=ScoutInsDrNavigator(load_gpx_route(route_path))
        ),
    }
    router_recorder = None
    if recorder:
        router_recorder = ApplicationRouterRecorder(
            routes_jsonl_path=record_dir / "application_router_benchmark_routes.jsonl",
            filter_outputs_jsonl_path=record_dir / "application_router_benchmark_filter_outputs.jsonl",
        )
    return ApplicationRouter(
        rules=default_application_route_rules(),
        registry=registry,
        recorder=router_recorder,
    )


def _measure_loop(*, iterations: int, action) -> list[int]:
    timings_ns: list[int] = []
    for index in range(iterations):
        start_ns = time.perf_counter_ns()
        action(index)
        timings_ns.append(time.perf_counter_ns() - start_ns)
    return timings_ns


def _record_dispatch_counts(records: list[Any], *, status_counts: dict[str, int], route_target_counts: dict[str, int]) -> None:
    for record in records:
        status = str(record.dispatch_status.value)
        target = str(record.route_target.value)
        status_counts[status] = status_counts.get(status, 0) + 1
        route_target_counts[target] = route_target_counts.get(target, 0) + 1


def _benchmark_report(
    *,
    scenario: str,
    iterations: int,
    timings_ns: list[int],
    status_counts: dict[str, int],
    route_target_counts: dict[str, int],
    record_dir: Path,
) -> dict[str, Any]:
    total_ns = sum(timings_ns)
    total_s = total_ns / 1_000_000_000
    latencies_ms = [value / 1_000_000 for value in timings_ns]
    messages_per_second = iterations / total_s if total_s > 0 else math.inf
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "scenario": scenario,
        "iterations": iterations,
        "messages_per_second": messages_per_second,
        "stable_hz_budget_50pct": messages_per_second * 0.5,
        "stable_hz_budget_20pct": messages_per_second * 0.2,
        "latency_ms": {
            "min": min(latencies_ms),
            "avg": statistics.fmean(latencies_ms),
            "p50": _percentile(latencies_ms, 50),
            "p95": _percentile(latencies_ms, 95),
            "max": max(latencies_ms),
        },
        "dispatch_status_counts": status_counts,
        "route_target_counts": route_target_counts,
        "record_dir": str(record_dir),
        "boundary": {
            "safety_api_called": False,
            "phase1_l0_l4_state_mutated": False,
            "outbound_send_performed": False,
            "hardware_control_performed": False,
        },
    }


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _acc_observation(index: int) -> ApplicationObservation:
    return ApplicationObservation(
        observation_id=f"bench-acc-{index}",
        source_adapter="wearable-benchmark",
        ingress_transport=IngressTransport.LAN_HTTP,
        observation_name="customMotionPacket",
        values={"acc_x": 0.01, "acc_y": -0.02, "acc_z": 9.81},
        received_at="2026-06-05T00:00:00Z",
        raw_evidence_refs=(f"bench.acc.{index}",),
    )


def _location_observation(index: int, *, lat: float, lon: float) -> ApplicationObservation:
    return ApplicationObservation(
        observation_id=f"bench-location-{index}",
        source_adapter="wearable-benchmark",
        ingress_transport=IngressTransport.LAN_HTTP,
        observation_name="location",
        values={"latitude": lat, "longitude": lon, "horizontalAccuracy": 5.0},
        received_at="2026-06-05T00:00:00Z",
        raw_evidence_refs=(f"bench.location.{index}",),
    )


def _pdr_observation(index: int, *, distance_m: float) -> ApplicationObservation:
    return ApplicationObservation(
        observation_id=f"bench-pdr-{index}",
        source_adapter="wearable-benchmark",
        ingress_transport=IngressTransport.LAN_HTTP,
        observation_name="pedometer",
        values={"pedometerDistance": distance_m},
        timestamp_s=1780555780.0 + index,
        received_at="2026-06-05T00:00:00Z",
        raw_evidence_refs=(f"bench.pdr.{index}",),
    )


def _sensorlogger_message(index: int, *, lat: float, lon: float) -> dict[str, Any]:
    return {
        "messageId": index,
        "sessionId": "benchmark-session",
        "deviceId": "benchmark-watch",
        "payload": [
            {
                "name": "location",
                "time": 1780555780000000000 + index * 10_000_000,
                "values": {
                    "latitude": lat,
                    "longitude": lon,
                    "horizontalAccuracy": 5.0,
                },
            },
            {
                "name": "customMotionPacket",
                "time": 1780555780000000000 + index * 10_000_000,
                "values": {"acc_x": 0.01, "acc_y": -0.02, "acc_z": 9.81},
            },
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark Scout application router throughput.")
    parser.add_argument(
        "--scenario",
        choices=[
            "rule_match",
            "router_no_recorder_acc",
            "router_jsonl_acc",
            "router_jsonl_pdr_estimate",
            "observer_jsonl_location_acc",
        ],
        default="router_jsonl_acc",
    )
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--route", type=Path, default=DEFAULT_ROUTE_PATH)
    parser.add_argument("--record-dir", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    report = run_benchmark(
        scenario=args.scenario,
        iterations=args.iterations,
        route_path=args.route,
        record_dir=args.record_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
