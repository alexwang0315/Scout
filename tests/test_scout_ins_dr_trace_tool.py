from __future__ import annotations

import json
from pathlib import Path

from scout_ins_dr_trace_tool import (
    INS_DR_TRACE_TOOL_ID,
    analyze_scout_ins_dr_trace,
)


def test_analyze_ins_dr_trace_returns_deviation_dropout_and_boundary(tmp_path: Path) -> None:
    project_root = tmp_path / "trip"
    output_dir = project_root / "outputs" / "navigation"
    output_dir.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "trace_fixture"}, ensure_ascii=False),
        encoding="utf-8",
    )
    estimates_path = output_dir / "ins_dr_estimates.jsonl"
    _write_jsonl(
        estimates_path,
        [
            {
                "timestamp_s": 0,
                "gps_lat": 24.0,
                "gps_lon": 121.0,
                "gps_horizontal_accuracy_m": 4.0,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "gnss_anchor",
                "raw_imu": {"acc_x": 0.0, "acc_y": 0.0, "acc_z": 9.8},
            },
            {
                "timestamp_s": 1,
                "gps_lat": 24.0,
                "gps_lon": 121.0001,
                "gps_horizontal_accuracy_m": 5.0,
                "estimate_lat": 24.001,
                "estimate_lon": 121.0001,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "dead_reckoning",
                "pdr_delta_m": 11.0,
                "confidence": 0.64,
            },
            {
                "timestamp_s": 2,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "dead_reckoning",
                "pdr_delta_m": 10.0,
            },
            {
                "timestamp_s": 3,
                "estimate_lat": 24.001,
                "estimate_lon": 121.0001,
                "estimate_source": "hiwonder_vendor_fused",
                "primary_truth_source": "vendor_fused",
                "pdr_delta_m": 10.0,
            },
            {
                "timestamp_s": 4,
                "gps_lat": 24.0,
                "gps_lon": 121.0002,
                "gps_horizontal_accuracy_m": 4.0,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0002,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "gnss_anchor",
            },
        ],
    )

    payload = analyze_scout_ins_dr_trace(
        project_root,
        query="GPS-only 軌跡和 INS/DR 軌跡差多少？",
        limit=5,
    )

    assert payload["tool_id"] == INS_DR_TRACE_TOOL_ID
    assert payload["status"] == "completed"
    assert payload["answerability"] == "trace_metrics_available"
    assert payload["project_id"] == "trace_fixture"
    assert payload["record_count"] == 5
    assert payload["gps_sample_count"] == 3
    assert payload["ins_dr_sample_count"] == 5
    assert payload["paired_fix_count"] == 3
    assert payload["pdr_only_sample_count"] == 2
    assert payload["gps_dropout_segment_count"] == 1
    assert payload["gps_dropout_segments"][0]["point_count"] == 2
    assert payload["vendor_fused_count"] == 1
    assert payload["raw_imu_baseline_count"] == 1
    assert payload["metrics"]["max_deviation_m"] > 100.0
    assert payload["metrics"]["mean_deviation_m"] > 30.0
    assert payload["zigzag_summary"]["status"] == "possible_zigzag_detected"
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    serialized = json.dumps(payload)
    assert "acc_x" not in serialized
    assert "acc_y" not in serialized
    assert "acc_z" not in serialized


def test_analyze_ins_dr_trace_reports_missing_evidence(tmp_path: Path) -> None:
    project_root = tmp_path / "trip"
    project_root.mkdir()

    payload = analyze_scout_ins_dr_trace(project_root, query="沒有 GPS 的地方是否仍有 PDR/IMU？")

    assert payload["status"] == "missing_trace_evidence"
    assert payload["answerability"] == "missing_trace_evidence"
    assert "ins_dr_estimates_jsonl" in payload["missing_fields"]
    assert "gps_only_trajectory" in payload["missing_fields"]
    assert payload["boundary"]["phase1_safety_mutation_allowed"] is False


def test_analyze_ins_dr_trace_discovers_saved_synthetic_context_without_claiming_live(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "trip"
    evidence_path = (
        project_root
        / "outputs"
        / "evals"
        / "synthetic_context"
        / "aihat2_ins_dr_trace.jsonl"
    )
    evidence_path.parent.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "saved_trace_fixture"}), encoding="utf-8"
    )
    _write_jsonl(
        evidence_path,
        [
            {
                "timestamp_s": 0,
                "gps_lat": 24.0,
                "gps_lon": 121.0,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0,
                "estimate_source": "synthetic_aihat2_route_constrained",
            },
            {
                "timestamp_s": 5,
                "estimate_lat": 24.0001,
                "estimate_lon": 121.0001,
                "estimate_source": "synthetic_aihat2_dead_reckoning",
                "pdr_delta_m": 12.0,
            },
        ],
    )

    monkeypatch.chdir(tmp_path)
    payload = analyze_scout_ins_dr_trace(
        Path("trip"),
        query="workspace 保存了哪些 GNSS、IMU、PDR sensor snapshot？",
    )

    assert payload["status"] == "completed"
    assert payload["record_count"] == 2
    assert payload["gps_sample_count"] == 1
    assert payload["ins_dr_sample_count"] == 2
    assert payload["pdr_only_sample_count"] == 1
    loaded = [item for item in payload["source_report"] if item["status"] == "loaded"]
    assert loaded[0]["source_kind"] == "synthetic_aihat2_eval_trace"
    assert loaded[0]["synthetic"] is True
    assert loaded[0]["source_ref"] == (
        "outputs/evals/synthetic_context/aihat2_ins_dr_trace.jsonl"
    )
    assert "合成評估 fixture" in payload["field_answer"]
    assert "synthetic eval trace 來源" in payload["field_answer"]
    assert "不是 live sensor snapshot" in payload["field_answer"]
    assert "共 2 筆" in payload["field_answer"]
    assert "PDR-only 樣本 1" in payload["field_answer"]
    assert "INS/DR trace decision" not in payload["field_answer"]
    assert payload["field_answer_priority"] == 100
    assert payload["field_answer_source_ref"] == (
        "outputs/evals/synthetic_context/aihat2_ins_dr_trace.jsonl"
    )
    assert payload["source_ref"] == payload["field_answer_source_ref"]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
