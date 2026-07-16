from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

from geo_utils import haversine_m


INS_DR_TRACE_TOOL_ID = "scout.ai.ins_dr_trace.analyze.v0"
INS_DR_TRACE_OUTPUT_KIND = "scout_ai_ins_dr_trace_tool_output"

DEFAULT_MAX_RECORDS = 1000
MAX_MAX_RECORDS = 5000
DEFAULT_RESULT_LIMIT = 6
MAX_RESULT_LIMIT = 20

_INS_DR_SOURCE_FRAGMENTS = (
    "ins",
    "dr",
    "pdr",
    "dead_reckoning",
    "route_constrained",
    "wearable",
    "hiwonder",
    "vendor",
    "fused",
)
_GPS_SOURCE_FRAGMENTS = ("gps", "gnss", "fix")
_VENDOR_FUSION_FRAGMENTS = ("vendor", "hiwonder", "module_fused", "vendor_fused")


def analyze_scout_ins_dr_trace(
    project_root: Path | str,
    *,
    query: str = "",
    estimates_path: str | Path | None = None,
    gps_path: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    max_records: int | str | None = DEFAULT_MAX_RECORDS,
    max_horizontal_accuracy_m: float | int | str | None = 25.0,
    max_interpolation_gap_s: float | int | str | None = 10.0,
    limit: int | str | None = DEFAULT_RESULT_LIMIT,
) -> dict[str, Any]:
    """Analyze already-recorded GPS and INS/DR/PDR traces.

    The tool is intentionally read-only and only summarizes bounded JSON/JSONL
    evidence. It does not run live hardware reads, generate safety decisions, or
    write trajectory reports.
    """

    root = Path(project_root).expanduser().resolve()
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    record_limit = _bounded_int(max_records, default=DEFAULT_MAX_RECORDS, maximum=MAX_MAX_RECORDS)
    result_limit = _bounded_int(limit, default=DEFAULT_RESULT_LIMIT, maximum=MAX_RESULT_LIMIT)
    accuracy_limit = _float_or_none(max_horizontal_accuracy_m)
    interpolation_gap_s = _float_or_none(max_interpolation_gap_s) or 10.0

    sources = _candidate_sources(
        root,
        estimates_path=estimates_path,
        gps_path=gps_path,
        evidence_dir=evidence_dir,
    )
    loaded_samples: list[dict[str, Any]] = []
    source_report: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    for source_path, source_kind in sources:
        resolved = _resolve_project_path(root, source_path)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        if not resolved.exists():
            source_report.append(
                {
                    "source_kind": source_kind,
                    "status": "missing",
                    "source_path": str(source_path),
                    "loaded_count": 0,
                }
            )
            continue
        samples, report = _load_trace_samples(
            resolved,
            source_kind=source_kind,
            max_records=max(0, record_limit - len(loaded_samples)),
            max_horizontal_accuracy_m=accuracy_limit,
        )
        try:
            report["source_ref"] = str(resolved.relative_to(root))
        except ValueError:
            report["source_ref"] = str(resolved)
        loaded_samples.extend(samples)
        source_report.append(report)
        if len(loaded_samples) >= record_limit:
            break

    loaded_samples.sort(key=_sample_sort_key)
    gps_samples = [sample for sample in loaded_samples if sample.get("gps")]
    estimate_samples = [sample for sample in loaded_samples if sample.get("estimate")]
    paired = _paired_deviation_samples(
        loaded_samples,
        gps_samples=gps_samples,
        estimate_samples=estimate_samples,
        max_interpolation_gap_s=interpolation_gap_s,
        limit=result_limit,
    )
    dropout_segments = _gps_dropout_segments(loaded_samples, limit=result_limit)
    zigzag = _zigzag_summary(estimate_samples)
    cadence = _cadence_summary(estimate_samples)
    answerability = _answerability(
        loaded_samples=loaded_samples,
        gps_samples=gps_samples,
        estimate_samples=estimate_samples,
        paired=paired,
    )
    metrics = _deviation_metrics(paired)
    missing_fields = _missing_fields_for_answerability(answerability)
    decision = _ins_dr_decision(
        answerability=answerability,
        metrics=metrics,
        dropout_segments=dropout_segments,
        zigzag=zigzag,
        missing_fields=missing_fields,
        vendor_fused_count=sum(1 for sample in estimate_samples if sample.get("vendor_fused")),
        pdr_only_sample_count=sum(
            1 for sample in loaded_samples if sample.get("estimate") and not sample.get("gps")
        ),
    )
    field_answer = _field_answer(
        query=query,
        decision=decision,
        metrics=metrics,
        missing_fields=missing_fields,
        source_report=source_report,
        record_count=len(loaded_samples),
        gps_sample_count=len(gps_samples),
        ins_dr_sample_count=len(estimate_samples),
        pdr_only_sample_count=sum(
            1
            for sample in loaded_samples
            if sample.get("estimate") and not sample.get("gps")
        ),
        raw_imu_baseline_count=sum(
            1 for sample in loaded_samples if sample.get("has_raw_imu")
        ),
    )
    decision_output = _decision_output(
        decision=decision,
        metrics=metrics,
        dropout_segments=dropout_segments,
        zigzag=zigzag,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )
    field_answer_source_ref = next(
        (
            str(item.get("source_ref"))
            for item in source_report
            if isinstance(item, dict) and item.get("source_ref")
        ),
        None,
    )

    return {
        "tool_id": INS_DR_TRACE_TOOL_ID,
        "status": "completed" if loaded_samples else "missing_trace_evidence",
        "project_id": project_id,
        "query": query,
        "analysis_kind": "read_only_ins_dr_trace",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision["decision"],
        "decision_output": decision_output,
        "field_answer": field_answer,
        "field_answer_priority": 100 if loaded_samples else 0,
        "field_answer_source_ref": field_answer_source_ref,
        "source_ref": field_answer_source_ref,
        "record_count": len(loaded_samples),
        "result_count": 1,
        "gps_sample_count": len(gps_samples),
        "ins_dr_sample_count": len(estimate_samples),
        "paired_fix_count": len(paired),
        "pdr_only_sample_count": sum(
            1 for sample in loaded_samples if sample.get("estimate") and not sample.get("gps")
        ),
        "vendor_fused_count": sum(1 for sample in estimate_samples if sample.get("vendor_fused")),
        "raw_imu_baseline_count": sum(1 for sample in loaded_samples if sample.get("has_raw_imu")),
        "metrics": metrics,
        "top_deviations": paired[:result_limit],
        "gps_dropout_segment_count": len(dropout_segments),
        "gps_dropout_segments": dropout_segments[:result_limit],
        "zigzag_summary": zigzag,
        "estimate_cadence_summary": cadence,
        "missing_fields": missing_fields,
        "ins_dr_trace": {
            "role": "Navigation Truth / INS-DR Trace Guard",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision["decision"],
            "decision_output": decision_output,
            "metrics": metrics,
            "paired_fix_count": len(paired),
            "gps_dropout_segment_count": len(dropout_segments),
            "zigzag_status": zigzag.get("status"),
            "next_action": decision["next_action"],
        },
        "source_report": source_report,
        "results": [
            {
                "label": "INS/DR trace summary",
                "decision": decision["decision"],
                "decision_output": decision_output,
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "snippet": _summary_snippet(
                    answerability=answerability,
                    paired_count=len(paired),
                    metrics=metrics,
                    dropout_count=len(dropout_segments),
                    zigzag=zigzag,
                ),
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 11 Navigation & Terrain Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19.2 required on-route output",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "boundary": _closed_boundary(),
    }


def _candidate_sources(
    root: Path,
    *,
    estimates_path: str | Path | None,
    gps_path: str | Path | None,
    evidence_dir: str | Path | None,
) -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    if estimates_path is not None:
        sources.append((Path(estimates_path), "explicit_ins_dr_estimates"))
    if gps_path is not None:
        sources.append((Path(gps_path), "explicit_gps_trajectory"))
    if evidence_dir is not None:
        evidence = Path(evidence_dir)
        sources.extend(
            [
                (evidence / "estimates.jsonl", "evidence_dir_estimates"),
                (evidence / "ins_dr_estimates.jsonl", "evidence_dir_ins_dr_estimates"),
                (
                    evidence / "sensorlogger_mqtt_filter_outputs.jsonl",
                    "evidence_dir_filter_outputs",
                ),
            ]
        )

    sources.extend(
        [
            (root / "outputs/navigation/ins_dr_estimates.jsonl", "project_ins_dr_estimates"),
            (root / "outputs/navigation/estimates.jsonl", "project_navigation_estimates"),
            (root / "outputs/ins_dr/ins_dr_estimates.jsonl", "project_ins_dr_estimates"),
            (root / "outputs/ins_dr/estimates.jsonl", "project_ins_dr_estimates"),
            (
                root / "outputs/runtime/sensorlogger_mqtt_filter_outputs.jsonl",
                "project_filter_outputs",
            ),
            (
                root
                / "outputs/evals/synthetic_context/aihat2_ins_dr_trace.jsonl",
                "synthetic_aihat2_eval_trace",
            ),
            (
                root / "sensorlogger_mqtt_filter_outputs.jsonl",
                "project_filter_outputs",
            ),
        ]
    )
    return sources


def _load_trace_samples(
    path: Path,
    *,
    source_kind: str,
    max_records: int,
    max_horizontal_accuracy_m: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = _load_records(path, max_records=max_records)
    samples = []
    for index, record in enumerate(records, start=1):
        sample = _normalize_trace_sample(
            record,
            source_path=path,
            source_kind=source_kind,
            line_number=index,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        )
        if sample is not None:
            samples.append(sample)
    report = {
        "source_kind": source_kind,
        "status": "loaded",
        "source_path": str(path),
        "loaded_count": len(samples),
        "raw_record_count": len(records),
        "raw_payloads_embedded": False,
    }
    if source_kind == "synthetic_aihat2_eval_trace":
        report.update(
            {
                "synthetic": True,
                "live_sensor_snapshot": False,
                "evidence_role": "synthetic eval fixture",
            }
        )
    return samples, report


def _load_records(path: Path, *, max_records: int) -> list[dict[str, Any]]:
    if max_records <= 0:
        return []
    if path.suffix.lower() == ".jsonl":
        records = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if len(records) >= max_records:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if isinstance(payload, dict):
                    records.append(payload)
        return records

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload[:max_records] if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("records", "samples", "estimates", "imu_data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value[:max_records] if isinstance(item, dict)]
        return [payload]
    return []


def _normalize_trace_sample(
    record: dict[str, Any],
    *,
    source_path: Path,
    source_kind: str,
    line_number: int,
    max_horizontal_accuracy_m: float | None,
) -> dict[str, Any] | None:
    timestamp_s = _first_float(
        record,
        "timestamp_s",
        "estimate_timestamp_s",
        "time_s",
        "sensor_timestamp_s",
        "loggingTime",
        "timestamp",
    )
    gps = _extract_gps(record, max_horizontal_accuracy_m=max_horizontal_accuracy_m)
    estimate = _extract_estimate(record)
    has_pdr = estimate is not None and _has_pdr_evidence(record, estimate)
    has_raw_imu = _has_raw_imu_evidence(record)
    if gps is None and estimate is None and not has_pdr and not has_raw_imu:
        return None
    source_text = _source_text(record, estimate)
    return {
        "source_path": str(source_path),
        "source_kind": source_kind,
        "line_number": line_number,
        "timestamp_s": timestamp_s,
        "observed_at": _first_value(record, "observed_at", "captured_at", "timestamp"),
        "gps": gps,
        "estimate": estimate,
        "has_pdr": has_pdr,
        "has_raw_imu": has_raw_imu,
        "vendor_fused": _has_any_fragment(source_text, _VENDOR_FUSION_FRAGMENTS)
        or bool(record.get("vendor_fusion_used_as_primary_truth")),
    }


def _extract_gps(
    record: dict[str, Any],
    *,
    max_horizontal_accuracy_m: float | None,
) -> dict[str, Any] | None:
    containers = [
        record,
        _dict_or_empty(record.get("gps")),
        _dict_or_empty(record.get("gnss")),
        _dict_or_empty(record.get("gnss_fix")),
        _dict_or_empty(record.get("location")),
    ]
    lat = _first_float_from(containers, "gps_lat", "lat", "latitude", "locationLatitude")
    lon = _first_float_from(containers, "gps_lon", "lon", "longitude", "locationLongitude")
    accuracy = _first_float_from(
        containers,
        "gps_horizontal_accuracy_m",
        "horizontal_accuracy_m",
        "accuracy_m",
        "h_acc_m",
        "locationHorizontalAccuracy",
    )
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if max_horizontal_accuracy_m is not None and accuracy is not None and accuracy > max_horizontal_accuracy_m:
        return None
    valid = _gps_valid(record)
    if valid is False:
        return None
    return {
        "lat": lat,
        "lon": lon,
        "horizontal_accuracy_m": accuracy,
    }


def _extract_estimate(record: dict[str, Any]) -> dict[str, Any] | None:
    containers = [
        record,
        _dict_or_empty(record.get("estimate")),
        _dict_or_empty(record.get("ins_dr")),
        _dict_or_empty(record.get("navigation_estimate")),
        _dict_or_empty(record.get("pdr")),
        _dict_or_empty(record.get("position")),
    ]
    lat = _first_float_from(containers, "estimate_lat", "lat", "latitude")
    lon = _first_float_from(containers, "estimate_lon", "lon", "longitude")
    source_text = _source_text(record, None)
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if (
        "estimate_lat" not in record
        and "estimate_lon" not in record
        and not any(
            isinstance(record.get(key), dict)
            for key in ("estimate", "ins_dr", "navigation_estimate", "pdr")
        )
        and not _has_any_fragment(source_text, _INS_DR_SOURCE_FRAGMENTS)
    ):
        return None
    source = _first_str_from(containers, "estimate_source", "source", "provider")
    primary_truth_source = _first_str_from(containers, "primary_truth_source")
    return {
        "lat": lat,
        "lon": lon,
        "source": source,
        "primary_truth_source": primary_truth_source,
        "route_distance_m": _first_float_from(containers, "route_distance_m", "distance_m"),
        "progress_m": _first_float_from(containers, "progress_m", "route_progress_m"),
        "confidence": _first_float_from(containers, "confidence"),
        "uncertainty_m": _first_float_from(containers, "uncertainty_m", "estimated_error_m"),
        "heading_deg": _first_float_from(containers, "heading_deg", "heading"),
        "pdr_delta_m": _first_float_from(containers, "pdr_delta_m", "distance_delta_m"),
        "dr_elapsed_s": _first_float_from(containers, "dr_elapsed_s"),
        "dr_distance_since_anchor_m": _first_float_from(containers, "dr_distance_since_anchor_m"),
        "degraded": _first_value_from(containers, "degraded"),
        "degradation_reasons": _as_str_list(_first_value_from(containers, "degradation_reasons")),
        "raw_evidence_refs": _as_str_list(_first_value_from(containers, "raw_evidence_refs")),
    }


def _paired_deviation_samples(
    samples: list[dict[str, Any]],
    *,
    gps_samples: list[dict[str, Any]],
    estimate_samples: list[dict[str, Any]],
    max_interpolation_gap_s: float,
    limit: int,
) -> list[dict[str, Any]]:
    paired = []
    for sample in samples:
        gps = sample.get("gps")
        estimate = sample.get("estimate")
        if not gps or not estimate:
            continue
        paired.append(_deviation_item(sample, gps, estimate, interpolation_gap_s=0.0))

    if not paired:
        gps_track = [
            sample
            for sample in gps_samples
            if sample.get("timestamp_s") is not None and sample.get("gps")
        ]
        gps_track.sort(key=lambda item: float(item["timestamp_s"]))
        for estimate_sample in estimate_samples:
            estimate = estimate_sample.get("estimate")
            timestamp_s = estimate_sample.get("timestamp_s")
            if not estimate or timestamp_s is None:
                continue
            gps_match = _nearest_gps_sample(gps_track, float(timestamp_s), max_gap_s=max_interpolation_gap_s)
            if gps_match is None:
                continue
            paired.append(
                _deviation_item(
                    estimate_sample,
                    gps_match["gps"],
                    estimate,
                    interpolation_gap_s=abs(float(gps_match["timestamp_s"]) - float(timestamp_s)),
                )
            )

    paired.sort(key=lambda item: item["deviation_m"], reverse=True)
    return paired[: max(limit, 0)]


def _deviation_item(
    sample: dict[str, Any],
    gps: dict[str, Any],
    estimate: dict[str, Any],
    *,
    interpolation_gap_s: float,
) -> dict[str, Any]:
    deviation_m = haversine_m(gps["lat"], gps["lon"], estimate["lat"], estimate["lon"])
    return {
        "timestamp_s": sample.get("timestamp_s"),
        "line_number": sample.get("line_number"),
        "source_kind": sample.get("source_kind"),
        "deviation_m": round(deviation_m, 3),
        "gps_horizontal_accuracy_m": gps.get("horizontal_accuracy_m"),
        "gps_interpolation_gap_s": round(interpolation_gap_s, 3),
        "estimate_source": estimate.get("source"),
        "primary_truth_source": estimate.get("primary_truth_source"),
        "confidence": estimate.get("confidence"),
        "uncertainty_m": estimate.get("uncertainty_m"),
        "degraded": estimate.get("degraded"),
        "degradation_reasons": estimate.get("degradation_reasons") or [],
        "pdr_delta_m": estimate.get("pdr_delta_m"),
        "heading_deg": estimate.get("heading_deg"),
    }


def _nearest_gps_sample(
    gps_track: list[dict[str, Any]],
    timestamp_s: float,
    *,
    max_gap_s: float,
) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for sample in gps_track:
        gap = abs(float(sample["timestamp_s"]) - timestamp_s)
        if gap > max_gap_s:
            continue
        if best is None or gap < best[0]:
            best = (gap, sample)
    return best[1] if best is not None else None


def _deviation_metrics(paired: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(item["deviation_m"]) for item in paired]
    if not values:
        return {
            "count": 0,
            "max_deviation_m": None,
            "mean_deviation_m": None,
            "median_deviation_m": None,
            "p95_deviation_m": None,
        }
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(values),
        "max_deviation_m": round(max(values), 3),
        "mean_deviation_m": round(statistics.fmean(values), 3),
        "median_deviation_m": round(statistics.median(values), 3),
        "p95_deviation_m": round(ordered[p95_index], 3),
    }


def _gps_dropout_segments(samples: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    ordered = sorted(samples, key=_sample_sort_key)
    for sample in ordered:
        is_dropout = bool(sample.get("estimate")) and not bool(sample.get("gps"))
        if not is_dropout:
            if current is not None:
                segments.append(current)
                current = None
            continue
        if current is None:
            current = {
                "start_line_number": sample.get("line_number"),
                "end_line_number": sample.get("line_number"),
                "start_timestamp_s": sample.get("timestamp_s"),
                "end_timestamp_s": sample.get("timestamp_s"),
                "point_count": 0,
                "pdr_sample_count": 0,
                "raw_imu_sample_count": 0,
            }
        current["end_line_number"] = sample.get("line_number")
        current["end_timestamp_s"] = sample.get("timestamp_s")
        current["point_count"] += 1
        if sample.get("has_pdr"):
            current["pdr_sample_count"] += 1
        if sample.get("has_raw_imu"):
            current["raw_imu_sample_count"] += 1
    if current is not None:
        segments.append(current)
    return segments[: max(limit, 0)]


def _zigzag_summary(estimate_samples: list[dict[str, Any]]) -> dict[str, Any]:
    points = [
        sample
        for sample in sorted(estimate_samples, key=_sample_sort_key)
        if sample.get("estimate")
    ]
    bearings = []
    for before, after in zip(points, points[1:]):
        a = before["estimate"]
        b = after["estimate"]
        distance_m = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
        if distance_m < 0.75:
            continue
        bearings.append(_bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"]))
    reversal_count = 0
    max_turn_deg = 0.0
    for before, after in zip(bearings, bearings[1:]):
        turn = _angle_delta_deg(before, after)
        max_turn_deg = max(max_turn_deg, turn)
        if turn >= 100.0:
            reversal_count += 1
    return {
        "status": "possible_zigzag_detected" if reversal_count >= 2 else "not_detected",
        "segment_bearing_count": len(bearings),
        "large_turn_count": reversal_count,
        "max_turn_deg": round(max_turn_deg, 3),
        "method": "bearing reversal heuristic over consecutive estimate points",
    }


def _cadence_summary(estimate_samples: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [
        float(sample["timestamp_s"])
        for sample in sorted(estimate_samples, key=_sample_sort_key)
        if sample.get("timestamp_s") is not None
    ]
    intervals = [
        after - before
        for before, after in zip(timestamps, timestamps[1:])
        if after >= before
    ]
    if not intervals:
        return {
            "sample_count_with_timestamp": len(timestamps),
            "mean_interval_s": None,
            "max_interval_s": None,
            "estimated_hz": None,
        }
    mean_interval = statistics.fmean(intervals)
    return {
        "sample_count_with_timestamp": len(timestamps),
        "mean_interval_s": round(mean_interval, 3),
        "max_interval_s": round(max(intervals), 3),
        "estimated_hz": round(1.0 / mean_interval, 3) if mean_interval > 0 else None,
    }


def _answerability(
    *,
    loaded_samples: list[dict[str, Any]],
    gps_samples: list[dict[str, Any]],
    estimate_samples: list[dict[str, Any]],
    paired: list[dict[str, Any]],
) -> str:
    if not loaded_samples:
        return "missing_trace_evidence"
    if not estimate_samples:
        return "missing_ins_dr_estimates"
    if not gps_samples:
        return "missing_gps_trajectory"
    if not paired:
        return "insufficient_aligned_samples"
    return "trace_metrics_available"


def _missing_fields_for_answerability(answerability: str) -> list[str]:
    if answerability == "missing_trace_evidence":
        return ["ins_dr_estimates_jsonl", "gps_only_trajectory"]
    if answerability == "missing_ins_dr_estimates":
        return ["ins_dr_estimates_jsonl"]
    if answerability == "missing_gps_trajectory":
        return ["gps_only_trajectory"]
    if answerability == "insufficient_aligned_samples":
        return ["timestamp_alignment_or_paired_gps_estimate_samples"]
    return []


def _ins_dr_decision(
    *,
    answerability: str,
    metrics: dict[str, Any],
    dropout_segments: list[dict[str, Any]],
    zigzag: dict[str, Any],
    missing_fields: list[str],
    vendor_fused_count: int,
    pdr_only_sample_count: int,
) -> dict[str, Any]:
    if missing_fields:
        return {
            "decision": "DELAY",
            "main_reasons": [
                f"answerability={answerability}",
                "INS/DR and GPS evidence are not sufficiently aligned",
            ],
            "next_action": (
                "collect paired GPS and INS/DR samples before using this trace "
                "to answer route-fit or turn decisions"
            ),
            "action_limit": (
                "do not use missing or unpaired trace evidence to confirm route, "
                "turn, shortcut, off-route, or safety-state decisions"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    max_deviation = _metric_float(metrics, "max_deviation_m")
    mean_deviation = _metric_float(metrics, "mean_deviation_m")
    p95_deviation = _metric_float(metrics, "p95_deviation_m")
    zigzag_detected = zigzag.get("status") == "possible_zigzag_detected"
    dropout_count = len(dropout_segments)

    if (
        (max_deviation is not None and max_deviation >= 120.0)
        or (p95_deviation is not None and p95_deviation >= 90.0)
        or (zigzag_detected and dropout_count >= 1)
    ):
        return {
            "decision": "NO_GO",
            "main_reasons": _trace_reasons(
                metrics=metrics,
                dropout_count=dropout_count,
                zigzag_detected=zigzag_detected,
                vendor_fused_count=vendor_fused_count,
                pdr_only_sample_count=pdr_only_sample_count,
            ),
            "next_action": (
                "stop treating the INS/DR trace as route truth; re-anchor with "
                "GPS, map corridor, terrain, and the last trustworthy CP"
            ),
            "action_limit": (
                "do not continue, descend, shortcut, or mark route correctness "
                "from this trace until re-anchored"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    if (
        (max_deviation is not None and max_deviation >= 45.0)
        or (mean_deviation is not None and mean_deviation >= 25.0)
        or zigzag_detected
        or dropout_count >= 2
    ):
        return {
            "decision": "CHANGE_PLAN",
            "main_reasons": _trace_reasons(
                metrics=metrics,
                dropout_count=dropout_count,
                zigzag_detected=zigzag_detected,
                vendor_fused_count=vendor_fused_count,
                pdr_only_sample_count=pdr_only_sample_count,
            ),
            "next_action": (
                "slow down, re-anchor at a known CP or open-sky point, and compare "
                "GPS, INS/DR, GPX, heading, and map corridor before proceeding"
            ),
            "action_limit": (
                "do not use INS/DR alone for branch, off-route, or descent decisions"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    return {
        "decision": "CONDITIONAL_GO",
        "main_reasons": _trace_reasons(
            metrics=metrics,
            dropout_count=dropout_count,
            zigzag_detected=zigzag_detected,
            vendor_fused_count=vendor_fused_count,
            pdr_only_sample_count=pdr_only_sample_count,
        ),
        "next_action": (
            "use INS/DR as candidate navigation support only; keep cross-checking "
            "against GPS, route corridor, terrain, and CP timing"
        ),
        "action_limit": (
            "conditional reference only; no runtime safety truth or route permission "
            "is granted by trace metrics"
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _field_answer(
    *,
    query: str,
    decision: dict[str, Any],
    metrics: dict[str, Any],
    missing_fields: list[str],
    source_report: list[dict[str, Any]],
    record_count: int,
    gps_sample_count: int,
    ins_dr_sample_count: int,
    pdr_only_sample_count: int,
    raw_imu_baseline_count: int,
) -> str:
    reasons = [str(item) for item in decision.get("main_reasons") or [] if str(item)]
    if missing_fields:
        reasons.append("missing=" + ",".join(missing_fields))
    metric_text = (
        f"max_deviation_m={metrics.get('max_deviation_m')}; "
        f"mean_deviation_m={metrics.get('mean_deviation_m')}; "
        f"p95_deviation_m={metrics.get('p95_deviation_m')}"
    )
    loaded_sources = [
        item for item in source_report if item.get("status") == "loaded"
    ]
    source_refs = [
        str(item.get("source_ref") or item.get("source_path"))
        for item in loaded_sources
    ]
    synthetic_sources = [item for item in loaded_sources if item.get("synthetic")]
    saved_evidence = (
        f"Saved trace evidence: sources={len(loaded_sources)}, records={record_count}, "
        f"GNSS/GPS samples={gps_sample_count}, INS/DR samples={ins_dr_sample_count}, "
        f"PDR-only samples={pdr_only_sample_count}, raw-IMU baselines="
        f"{raw_imu_baseline_count}; source_refs={','.join(source_refs) or 'none'}. "
    )
    if synthetic_sources:
        saved_evidence += (
            "The loaded source is a synthetic eval fixture, not a live sensor "
            "snapshot; no live GNSS/IMU/PDR capture is proven. "
        )
    if re.search(
        r"(?:workspace|保存|stored|saved).*(?:gnss|gps|imu|pdr|sensor|snapshot)",
        query,
        re.IGNORECASE,
    ):
        synthetic_note = (
            "這是合成評估 fixture，不是 live sensor snapshot；"
            "尚無真實即時 GNSS/IMU/PDR capture 證據。"
            if synthetic_sources
            else ""
        )
        source_kind = "synthetic eval trace" if synthetic_sources else "trace"
        return (
            f"Workspace 已保存 {len(loaded_sources)} 個 {source_kind} 來源、"
            f"共 {record_count} 筆；"
            f"GNSS/GPS 樣本 {gps_sample_count}、INS/DR 樣本 {ins_dr_sample_count}、"
            f"PDR-only 樣本 {pdr_only_sample_count}、raw-IMU 基線 "
            f"{raw_imu_baseline_count}。source_ref="
            f"{','.join(source_refs) or 'none'}。{synthetic_note}"
        )
    return (
        saved_evidence
        + f"INS/DR trace decision: {decision['decision']}. "
        + f"{metric_text}. {'; '.join(reasons[:3])}. "
        + f"Next step: {decision['next_action']}. "
        + "This is candidate navigation evidence only, not runtime safety truth; "
        + "it cannot trigger Ln, /safety/*, SOS, outbound send, or hardware control."
    )


def _decision_output(
    *,
    decision: dict[str, Any],
    metrics: dict[str, Any],
    dropout_segments: list[dict[str, Any]],
    zigzag: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    decision_label = str(decision["decision"])
    allowed = decision_label in {"GO", "CONDITIONAL_GO"}
    reasons = [str(item) for item in decision.get("main_reasons") or [] if str(item)]
    if not reasons:
        reasons = ["INS/DR trace did not expose a decision reason"]
    uncertainty_notes = _uncertainty_notes(
        decision=decision_label,
        dropout_segments=dropout_segments,
        zigzag=zigzag,
        missing_fields=missing_fields,
    )
    first_layer = {
        "decision": _decision_phrase(decision_label),
        "limit": str(decision["action_limit"]),
        "reason": " / ".join(reasons[:2]),
        "nextStep": str(decision["next_action"]),
    }
    residual_risk = [
        "INS/DR, PDR, and vendor-fused traces are candidate navigation evidence only.",
        (
            "GPS, route corridor, terrain, weather, and CP context remain separate "
            "decision inputs."
        ),
        (
            "No runtime safety truth, /safety/*, Ln, SOS, outbound send, or "
            "hardware control was triggered."
        ),
    ]
    return {
        "role": "Navigation Truth / INS-DR Trace Guard",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {first_layer['decision']}",
                f"[限制] {first_layer['limit']}",
                f"[原因] {first_layer['reason']}",
                f"[下一步] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": {
            "details": _decision_details(
                metrics=metrics,
                dropout_segments=dropout_segments,
                zigzag=zigzag,
                field_answer=field_answer,
            ),
            "uncertaintyNotes": uncertainty_notes,
            "residualRisk": residual_risk,
            "requiredConditions": _required_conditions(
                decision=decision_label,
                missing_fields=missing_fields,
            ),
            "alternativeActions": _alternative_actions(decision_label),
        },
        "action": "navigation_trace_reference",
        "decision": decision_label,
        "allowed": allowed,
        "locationConstraint": "candidate trace metrics only; verify against route corridor",
        "mainReasons": reasons[:3],
        "cost": {
            "timeBufferChangeMinutes": 0,
            "attentionImpact": (
                "Trace review consumes attention; stop or slow down before "
                "re-anchoring if uncertainty is high."
            ),
            "retreatImpact": (
                "Do not consume retreat buffer by expanding route uncertainty "
                "from an unverified trace."
            ),
        },
        "nextAction": first_layer["nextStep"],
        "confidence": _confidence(
            decision=decision_label,
            uncertainty_notes=uncertainty_notes,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": _required_conditions(
            decision=decision_label,
            missing_fields=missing_fields,
        ),
        "alternativeActions": _alternative_actions(decision_label),
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 11 Navigation & Terrain Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19.2 required on-route output",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 MUST/MUST NOT",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _trace_reasons(
    *,
    metrics: dict[str, Any],
    dropout_count: int,
    zigzag_detected: bool,
    vendor_fused_count: int,
    pdr_only_sample_count: int,
) -> list[str]:
    reasons = []
    for key in ("max_deviation_m", "mean_deviation_m", "p95_deviation_m"):
        value = metrics.get(key)
        if value is not None:
            reasons.append(f"{key}={value}")
    if dropout_count:
        reasons.append(f"gps_dropout_segments={dropout_count}")
    if zigzag_detected:
        reasons.append("possible_zigzag_detected")
    if vendor_fused_count:
        reasons.append(f"vendor_fused_count={vendor_fused_count}")
    if pdr_only_sample_count:
        reasons.append(f"pdr_only_sample_count={pdr_only_sample_count}")
    return reasons or ["trace metrics are within candidate thresholds"]


def _decision_phrase(decision: str) -> str:
    if decision == "CONDITIONAL_GO":
        return "可作為候選導航參考。"
    if decision == "CHANGE_PLAN":
        return "先修正定位策略。"
    if decision == "NO_GO":
        return "不要依此 trace 繼續前進。"
    if decision == "DELAY":
        return "暫緩 INS/DR trace 判斷。"
    if decision == "ESCALATE":
        return "需要升級導航判斷。"
    return "可作為參考。"


def _uncertainty_notes(
    *,
    decision: str,
    dropout_segments: list[dict[str, Any]],
    zigzag: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    notes = []
    if missing_fields:
        notes.append("Missing fields: " + ", ".join(missing_fields))
    if dropout_segments:
        notes.append(
            f"GPS dropout segment count={len(dropout_segments)}; INS/DR may drift."
        )
    if zigzag.get("status") == "possible_zigzag_detected":
        notes.append("Possible zigzag or bearing reversal detected.")
    if decision in {"CHANGE_PLAN", "NO_GO"}:
        notes.append("Do not rely on INS/DR alone for route-fit decisions.")
    notes.append("Trace analysis is read-only and does not inspect live hardware.")
    return notes


def _required_conditions(*, decision: str, missing_fields: list[str]) -> list[str]:
    if missing_fields:
        return [
            "Provide " + ", ".join(missing_fields),
            "Pair GPS and INS/DR samples within the accepted timestamp gap.",
            "Re-run trace analysis before using the trace for navigation context.",
        ]
    conditions = [
        "Cross-check INS/DR against GPS, GPX route corridor, terrain, and CP context.",
        "Keep trace metrics as candidate navigation evidence only.",
        "Do not call /safety/*, trigger Ln, send outbound, or control hardware.",
    ]
    if decision in {"CHANGE_PLAN", "NO_GO"}:
        conditions.insert(0, "Re-anchor at a trusted CP, open-sky fix, or known route corridor.")
    return conditions


def _alternative_actions(decision: str) -> list[str]:
    if decision == "DELAY":
        return [
            "collect paired GPS and INS/DR samples",
            "ask live navigation state after obtaining a reliable fix",
            "use map/GPX evidence instead of an unpaired trace",
        ]
    if decision == "NO_GO":
        return [
            "stop and re-anchor",
            "return to last trustworthy CP",
            "switch to conservative route-corridor verification",
        ]
    if decision == "CHANGE_PLAN":
        return [
            "slow down and re-anchor",
            "compare GPS, INS/DR, GPX, and terrain",
            "avoid off-route or descent decisions until aligned",
        ]
    return [
        "use trace as candidate support only",
        "continue cross-checking GPS and route corridor",
        "ask contextual permission before stopping, rerouting, or leaving the path",
    ]


def _decision_details(
    *,
    metrics: dict[str, Any],
    dropout_segments: list[dict[str, Any]],
    zigzag: dict[str, Any],
    field_answer: str,
) -> list[str]:
    details = [
        field_answer,
        (
            f"deviation_count={metrics.get('count')}; "
            f"max={metrics.get('max_deviation_m')}; "
            f"mean={metrics.get('mean_deviation_m')}; "
            f"p95={metrics.get('p95_deviation_m')}"
        ),
        (
            f"gps_dropout_segments={len(dropout_segments)}; "
            f"zigzag_status={zigzag.get('status')}"
        ),
    ]
    for item in dropout_segments[:2]:
        details.append(
            "dropout "
            f"lines={item.get('start_line_number')}-{item.get('end_line_number')} "
            f"points={item.get('point_count')}"
        )
    return details


def _confidence(*, decision: str, uncertainty_notes: list[str]) -> str:
    if decision in {"DELAY", "NO_GO"}:
        return "low"
    if decision == "CHANGE_PLAN" or uncertainty_notes:
        return "medium"
    return "high"


def _metric_float(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _summary_snippet(
    *,
    answerability: str,
    paired_count: int,
    metrics: dict[str, Any],
    dropout_count: int,
    zigzag: dict[str, Any],
) -> str:
    if answerability != "trace_metrics_available":
        return f"answerability={answerability}; missing={','.join(_missing_fields_for_answerability(answerability))}"
    return (
        f"paired={paired_count}; max_deviation_m={metrics.get('max_deviation_m')}; "
        f"mean_deviation_m={metrics.get('mean_deviation_m')}; "
        f"gps_dropout_segments={dropout_count}; zigzag={zigzag.get('status')}"
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve_project_path(root: Path, path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    root_expanded = root.expanduser()
    if expanded == root_expanded or expanded.is_relative_to(root_expanded):
        return expanded.resolve()
    return (root / expanded).resolve()


def _sample_sort_key(sample: dict[str, Any]) -> tuple[float, int]:
    timestamp = sample.get("timestamp_s")
    if timestamp is not None:
        return (float(timestamp), int(sample.get("line_number") or 0))
    return (float("inf"), int(sample.get("line_number") or 0))


def _first_float(record: dict[str, Any], *keys: str) -> float | None:
    return _first_float_from([record], *keys)


def _first_float_from(containers: list[dict[str, Any]], *keys: str) -> float | None:
    value = _first_value_from(containers, *keys)
    return _float_or_none(value)


def _first_str_from(containers: list[dict[str, Any]], *keys: str) -> str | None:
    value = _first_value_from(containers, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_value(record: dict[str, Any], *keys: str) -> Any:
    return _first_value_from([record], *keys)


def _first_value_from(containers: list[dict[str, Any]], *keys: str) -> Any:
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value is not None and value != "":
                return value
    return None


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _bounded_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, parsed))


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _source_text(record: dict[str, Any], estimate: dict[str, Any] | None) -> str:
    parts = [
        record.get("source"),
        record.get("estimate_source"),
        record.get("primary_truth_source"),
        record.get("provider"),
        record.get("route_target"),
    ]
    if estimate:
        parts.extend([estimate.get("source"), estimate.get("primary_truth_source")])
    return " ".join(str(part).lower() for part in parts if part is not None)


def _has_any_fragment(text: str, fragments: tuple[str, ...]) -> bool:
    normalized = str(text).lower()
    return any(fragment in normalized for fragment in fragments)


def _gps_valid(record: dict[str, Any]) -> bool | None:
    for key in ("gps_valid", "gnss_valid", "valid", "has_fix"):
        value = record.get(key)
        if isinstance(value, bool):
            return value
    fix_quality = record.get("fix_quality")
    if fix_quality is not None:
        normalized = str(fix_quality).strip().lower()
        return normalized not in {"0", "invalid", "none", "no_fix", "false"}
    return None


def _has_pdr_evidence(record: dict[str, Any], estimate: dict[str, Any]) -> bool:
    if estimate.get("pdr_delta_m") is not None:
        return True
    source = _source_text(record, estimate)
    return "pdr" in source or "dead_reckoning" in source or "wearable" in source


def _has_raw_imu_evidence(record: dict[str, Any]) -> bool:
    if isinstance(record.get("raw_imu"), dict) or isinstance(record.get("imu"), dict):
        return True
    keys = set(record)
    imu_key_fragments = (
        "acc_x",
        "acc_y",
        "acc_z",
        "gyro_x",
        "gyro_y",
        "gyro_z",
        "accelerometer",
        "gyroscope",
        "rotationRate",
    )
    return any(any(fragment in key for fragment in imu_key_fragments) for key in keys)


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _angle_delta_deg(a: float, b: float) -> float:
    return abs((b - a + 180.0) % 360.0 - 180.0)


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "live_hardware_read_performed": False,
    }
