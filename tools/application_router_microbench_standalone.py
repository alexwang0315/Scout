#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any


ARTIFACT_KIND = "scout_application_router_microbench"
ARTIFACT_VERSION = "application_router_microbench.v0"

INS_DR_SELECTOR = {
    "observation_names": {
        "location",
        "pedometer",
        "accelerometer",
        "gyroscope",
        "magnetometer",
        "barometer",
        "motion",
    },
    "value_keys": {
        "latitude",
        "longitude",
        "locationlatitude",
        "locationlongitude",
        "pedometerdistance",
        "pedometernumberofsteps",
        "distance_delta_m",
    },
    "value_key_groups": (
        ("acc_x", "acc_y", "acc_z"),
        ("gyro_x", "gyro_y", "gyro_z"),
        ("latitude", "longitude"),
        ("locationlatitude", "locationlongitude"),
    ),
    "capability_tags": {"imu", "pdr", "gps", "location", "wheel"},
}


def run_microbench(*, scenario: str, iterations: int, record_dir: Path | None = None) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if record_dir is None:
        with tempfile.TemporaryDirectory(prefix="scout-router-microbench-") as tmpdir:
            return _run_microbench(scenario=scenario, iterations=iterations, record_dir=Path(tmpdir))
    return _run_microbench(scenario=scenario, iterations=iterations, record_dir=record_dir)


def _run_microbench(*, scenario: str, iterations: int, record_dir: Path) -> dict[str, Any]:
    record_dir.mkdir(parents=True, exist_ok=True)
    timings_ns: list[int] = []
    route_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    if scenario == "selector_only":
        observation = _acc_observation(0)
        timings_ns = _measure_loop(iterations, lambda index: _matches_ins_dr(observation))
    elif scenario == "jsonl_append":
        routes_path = record_dir / "microbench_routes.jsonl"
        outputs_path = record_dir / "microbench_outputs.jsonl"

        def action(index: int) -> None:
            observation = _acc_observation(index)
            match_reason = _matches_ins_dr(observation)
            if match_reason:
                _count(route_counts, "navigation.ins_dr")
                _count(status_counts, "deferred")
                _append_jsonl(
                    routes_path,
                    {
                        "route_id": "navigation.ins_dr.wearable_route_constrained.v0",
                        "route_target": "navigation.ins_dr",
                        "match_reason": match_reason,
                        "dispatch_status": "deferred",
                        "input_ref": observation["observation_id"],
                    },
                )
                _append_jsonl(
                    outputs_path,
                    {
                        "route_target": "navigation.ins_dr",
                        "output_kind": "navigation_input_observed",
                        "status": "no_usable_navigation_input",
                        "observation_id": observation["observation_id"],
                    },
                )

        timings_ns = _measure_loop(iterations, action)
    elif scenario == "observer_like":
        raw_path = record_dir / "microbench_raw.jsonl"
        index_path = record_dir / "microbench_index.jsonl"
        routes_path = record_dir / "microbench_routes.jsonl"
        outputs_path = record_dir / "microbench_outputs.jsonl"
        status_path = record_dir / "microbench_status.json"

        def action(index: int) -> None:
            raw_payload = json.dumps(_sensorlogger_message(index), separators=(",", ":"))
            message = json.loads(raw_payload)
            observation_ids: list[str] = []
            _append_jsonl(raw_path, {"ingress_id": f"ingress-{index}", "raw_payload_text": raw_payload})
            _append_jsonl(
                index_path,
                {
                    "ingress_id": f"ingress-{index}",
                    "message_id": message["messageId"],
                    "payload_count": len(message["payload"]),
                },
            )
            for payload_index, reading in enumerate(message["payload"]):
                observation = {
                    "observation_id": f"obs-{index}-{payload_index}",
                    "observation_name": reading["name"],
                    "values": reading["values"],
                    "capability_tags": _capability_tags(reading["name"], reading["values"]),
                }
                observation_ids.append(observation["observation_id"])
                match_reason = _matches_ins_dr(observation)
                if match_reason:
                    _count(route_counts, "navigation.ins_dr")
                    status = "accepted" if reading["name"] == "location" else "deferred"
                    _count(status_counts, status)
                    _append_jsonl(
                        routes_path,
                        {
                            "route_id": "navigation.ins_dr.wearable_route_constrained.v0",
                            "route_target": "navigation.ins_dr",
                            "match_reason": match_reason,
                            "dispatch_status": status,
                            "input_ref": observation["observation_id"],
                        },
                    )
                    _append_jsonl(
                        outputs_path,
                        {
                            "route_target": "navigation.ins_dr",
                            "output_kind": "navigation_estimate" if status == "accepted" else "navigation_input_observed",
                            "status": "estimate_produced" if status == "accepted" else "no_usable_navigation_input",
                            "observation_id": observation["observation_id"],
                        },
                    )
            status_payload = {
                "artifact_kind": "scout_router_microbench_status",
                "message_count": index + 1,
                "latest_observation_ids": observation_ids,
                "route_target_counts": route_counts,
                "dispatch_status_counts": status_counts,
            }
            status_path.write_text(json.dumps(status_payload, sort_keys=True), encoding="utf-8")

        timings_ns = _measure_loop(iterations, action)
    else:
        raise ValueError(f"unknown microbench scenario: {scenario}")

    return _report(
        scenario=scenario,
        iterations=iterations,
        timings_ns=timings_ns,
        record_dir=record_dir,
        route_counts=route_counts,
        status_counts=status_counts,
    )


def _matches_ins_dr(observation: dict[str, Any]) -> str | None:
    observation_name = str(observation["observation_name"]).lower()
    if observation_name in INS_DR_SELECTOR["observation_names"]:
        return f"observation_name:{observation['observation_name']}"

    value_keys = {str(key).lower() for key in observation.get("values", {})}
    matched_keys = sorted(INS_DR_SELECTOR["value_keys"].intersection(value_keys))
    if matched_keys:
        return f"value_keys:{','.join(matched_keys)}"

    for group in INS_DR_SELECTOR["value_key_groups"]:
        if all(key in value_keys for key in group):
            return f"value_key_group:{','.join(group)}"

    matched_tags = sorted(INS_DR_SELECTOR["capability_tags"].intersection(set(observation.get("capability_tags", ()))))
    if matched_tags:
        return f"capability_tags:{','.join(matched_tags)}"
    return None


def _measure_loop(iterations: int, action) -> list[int]:
    timings_ns: list[int] = []
    for index in range(iterations):
        start_ns = time.perf_counter_ns()
        action(index)
        timings_ns.append(time.perf_counter_ns() - start_ns)
    return timings_ns


def _report(
    *,
    scenario: str,
    iterations: int,
    timings_ns: list[int],
    record_dir: Path,
    route_counts: dict[str, int],
    status_counts: dict[str, int],
) -> dict[str, Any]:
    total_s = sum(timings_ns) / 1_000_000_000
    latencies_ms = [value / 1_000_000 for value in timings_ns]
    messages_per_second = iterations / total_s if total_s else math.inf
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
        "route_target_counts": route_counts,
        "dispatch_status_counts": status_counts,
        "record_dir": str(record_dir),
        "boundary": {
            "safety_api_called": False,
            "phase1_l0_l4_state_mutated": False,
            "outbound_send_performed": False,
            "hardware_control_performed": False,
        },
    }


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        handle.write("\n")


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _acc_observation(index: int) -> dict[str, Any]:
    return {
        "observation_id": f"bench-acc-{index}",
        "observation_name": "customMotionPacket",
        "values": {"acc_x": 0.01, "acc_y": -0.02, "acc_z": 9.81},
        "capability_tags": (),
    }


def _sensorlogger_message(index: int) -> dict[str, Any]:
    return {
        "messageId": index,
        "sessionId": "benchmark-session",
        "deviceId": "benchmark-watch",
        "payload": [
            {
                "name": "location",
                "time": 1780555780000000000 + index * 10_000_000,
                "values": {"latitude": 25.0635, "longitude": 121.654, "horizontalAccuracy": 5.0},
            },
            {
                "name": "customMotionPacket",
                "time": 1780555780000000000 + index * 10_000_000,
                "values": {"acc_x": 0.01, "acc_y": -0.02, "acc_z": 9.81},
            },
        ],
    }


def _capability_tags(name: str, values: dict[str, Any]) -> tuple[str, ...]:
    lower = name.lower()
    tags: set[str] = set()
    if lower in {"accelerometer", "gyroscope", "magnetometer", "barometer", "motion"}:
        tags.add("imu")
    if {"latitude", "longitude"}.issubset(values):
        tags.update({"gps", "location"})
    if lower == "pedometer":
        tags.add("pdr")
    return tuple(sorted(tags))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stdlib-only Scout router microbenchmark.")
    parser.add_argument("--scenario", choices=["selector_only", "jsonl_append", "observer_like"], default="observer_like")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--record-dir", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    report = run_microbench(scenario=args.scenario, iterations=args.iterations, record_dir=args.record_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
