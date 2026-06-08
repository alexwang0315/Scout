from __future__ import annotations

from pathlib import Path

from tools.application_router_benchmark import run_benchmark


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_application_router_benchmark_reports_rule_match_throughput(tmp_path: Path) -> None:
    report = run_benchmark(
        scenario="rule_match",
        iterations=5,
        route_path=ROUTE_PATH,
        record_dir=tmp_path,
    )

    assert report["artifact_kind"] == "scout_application_router_benchmark"
    assert report["scenario"] == "rule_match"
    assert report["iterations"] == 5
    assert report["messages_per_second"] > 0
    assert report["latency_ms"]["p95"] >= 0
    assert report["stable_hz_budget_20pct"] > 0
    assert report["boundary"]["safety_api_called"] is False
    assert report["boundary"]["outbound_send_performed"] is False


def test_application_router_benchmark_reports_jsonl_acc_dispatch(tmp_path: Path) -> None:
    report = run_benchmark(
        scenario="router_jsonl_acc",
        iterations=3,
        route_path=ROUTE_PATH,
        record_dir=tmp_path,
    )

    assert report["scenario"] == "router_jsonl_acc"
    assert report["dispatch_status_counts"] == {"deferred": 3}
    assert report["route_target_counts"] == {"navigation.ins_dr": 3}
    assert (tmp_path / "application_router_benchmark_routes.jsonl").exists()
    assert (tmp_path / "application_router_benchmark_filter_outputs.jsonl").exists()


def test_application_router_benchmark_reports_observer_end_to_end(tmp_path: Path) -> None:
    report = run_benchmark(
        scenario="observer_jsonl_location_acc",
        iterations=2,
        route_path=ROUTE_PATH,
        record_dir=tmp_path,
    )

    assert report["scenario"] == "observer_jsonl_location_acc"
    assert report["dispatch_status_counts"]["accepted"] == 2
    assert report["dispatch_status_counts"]["deferred"] == 2
    assert report["route_target_counts"] == {"navigation.ins_dr": 2}
    assert (tmp_path / "sensorlogger_mqtt_raw.jsonl").exists()
