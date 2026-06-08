from __future__ import annotations

from pathlib import Path

from tools.application_router_microbench_standalone import run_microbench


def test_standalone_microbench_reports_selector_only() -> None:
    report = run_microbench(scenario="selector_only", iterations=5)

    assert report["artifact_kind"] == "scout_application_router_microbench"
    assert report["scenario"] == "selector_only"
    assert report["iterations"] == 5
    assert report["messages_per_second"] > 0
    assert report["boundary"]["safety_api_called"] is False
    assert report["boundary"]["outbound_send_performed"] is False


def test_standalone_microbench_reports_observer_like_jsonl(tmp_path: Path) -> None:
    report = run_microbench(scenario="observer_like", iterations=3, record_dir=tmp_path)

    assert report["scenario"] == "observer_like"
    assert report["dispatch_status_counts"] == {"accepted": 3, "deferred": 3}
    assert report["route_target_counts"] == {"navigation.ins_dr": 6}
    assert (tmp_path / "microbench_raw.jsonl").exists()
    assert (tmp_path / "microbench_status.json").exists()
