from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from geo_utils import haversine_m
from offline_map import load_offline_map_context


DEFAULT_SEGMENTS = [
    {
        "id": "watch_260512_085237",
        "source_file": "PdrSample/stream Apple Watch 260512 08_52_37.json",
    },
    {
        "id": "watch_260512_093931",
        "source_file": "PdrSample/stream Apple Watch 260512 09_39_31.json",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate Scout 2026-05-12 field golden metrics.")
    parser.add_argument(
        "--map-context",
        default="tests/fixtures/maps/scout_260512_overpass_map_context.geojson",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default="tests/fixtures/field_cases/scout_260512_golden.json",
        type=Path,
    )
    parser.add_argument("--sample-stride", default=25, type=int)
    parser.add_argument("--representative-samples", default=16, type=int)
    args = parser.parse_args()

    context = load_offline_map_context(args.map_context)
    map_payload = json.loads(args.map_context.read_text(encoding="utf-8"))
    map_properties = map_payload.get("properties", {}) if isinstance(map_payload, dict) else {}
    segments = [
        _segment_metrics(
            segment_id=segment["id"],
            source_file=Path(segment["source_file"]),
            map_context=context,
            sample_stride=args.sample_stride,
            representative_samples=args.representative_samples,
        )
        for segment in DEFAULT_SEGMENTS
    ]

    output = {
        "case_id": "scout_260512_field_golden",
        "description": "2026-05-12 Apple Watch field exploration with Overpass-derived offline map corridors.",
        "generated_by": "generate_field_golden_case.py",
        "source_files": [segment["source_file"] for segment in DEFAULT_SEGMENTS],
        "map_context": str(args.map_context),
        "overpass_query": "tests/fixtures/maps/scout_260512_overpass_query.ql",
        "bbox": map_properties.get("bbox"),
        "map_context_summary": _map_context_summary(context),
        "segments": segments,
        "gap_between_segments": _gap_between_segments(segments),
        "acceptance": {
            "min_overpass_corridors": 600,
            "min_footway_corridors": 90,
            "min_path_corridors": 30,
            "min_steps_corridors": 15,
            "min_map_inside_with_hacc_pct": 0.97,
            "max_nearest_corridor_distance_p95_m": 13.0,
            "min_representative_samples_per_segment": 12,
        },
        "notes": [
            "Raw Apple Watch SensorLog files are local evidence and are not required by the regression test.",
            "The second segment intentionally preserves weak/noisy GPS behavior for later safety replay work.",
            "Wi-Fi fingerprint data is not part of this golden case; it should be joined later through a signal producer.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _segment_metrics(
    *,
    segment_id: str,
    source_file: Path,
    map_context: Any,
    sample_stride: int,
    representative_samples: int,
) -> dict[str, Any]:
    records = _load_records(source_file)
    valid_locations = [record for record in records if _lat_lon(record) is not None]
    sampled_locations = valid_locations[::sample_stride]
    map_samples = [_map_sample(record, map_context) for record in sampled_locations]
    map_samples = [sample for sample in map_samples if sample is not None]
    representatives = _representative_samples(valid_locations, map_context, representative_samples)

    start_time = _record_time(records[0])
    end_time = _record_time(records[-1])
    duration_s = (end_time - start_time).total_seconds()
    hacc = _float_values(valid_locations, "locationHorizontalAccuracy")
    altitude = _float_values(valid_locations, "locationAltitude")
    speeds = _float_values(valid_locations, "locationSpeed")
    course = _float_values(valid_locations, "locationCourse")
    heart_rates = _float_values(records, "heartRateBPM")
    battery = _float_values(records, "batteryLevel")
    pedometer = _float_values(records, "pedometerDistance")
    steps = _float_values(records, "pedometerNumberOfSteps")
    activity_counts = Counter(str(record.get("activity")) for record in records if record.get("activity") not in (None, "", "null"))
    nearest_distances = [sample["nearest_corridor_distance_m"] for sample in map_samples]
    inside_count = sum(1 for sample in map_samples if sample["inside_corridor"])
    inside_with_hacc_count = sum(1 for sample in map_samples if sample["inside_corridor_with_hacc"])

    metrics = {
        "id": segment_id,
        "source_file": str(source_file),
        "start_time": records[0].get("loggingTime"),
        "end_time": records[-1].get("loggingTime"),
        "duration_s": round(duration_s, 1),
        "records": len(records),
        "valid_location_records": len(valid_locations),
        "sample_rate_hz": round(len(records) / duration_s, 2) if duration_s > 0 else None,
        "gps_polyline_m": round(_polyline_distance(valid_locations), 1),
        "gps_polyline_acc_lte_20m_m": round(_polyline_distance([r for r in valid_locations if (_to_float(r.get("locationHorizontalAccuracy")) or 999) <= 20]), 1),
        "gps_polyline_acc_lte_5m_m": round(_polyline_distance([r for r in valid_locations if (_to_float(r.get("locationHorizontalAccuracy")) or 999) <= 5]), 1),
        "net_displacement_m": round(_record_distance(valid_locations[0], valid_locations[-1]), 1),
        "pedometer_delta_m": round(_delta(pedometer), 1),
        "steps_delta": int(round(_delta(steps))),
        "horizontal_accuracy_median_m": round(statistics.median(hacc), 2),
        "horizontal_accuracy_p90_m": round(_percentile(hacc, 0.9), 2),
        "horizontal_accuracy_max_m": round(max(hacc), 2),
        "activity_majority": activity_counts.most_common(1)[0][0] if activity_counts else "unknown",
        "heart_rate_min_bpm": int(round(min(heart_rates))),
        "heart_rate_max_bpm": int(round(max(heart_rates))),
        "battery_start": round(battery[0], 2),
        "battery_end": round(battery[-1], 2),
        "map_sampled_points": len(map_samples),
        "map_inside_corridor_pct": round(inside_count / len(map_samples), 3),
        "map_inside_corridor_with_hacc_pct": round(inside_with_hacc_count / len(map_samples), 3),
        "nearest_corridor_distance_p50_m": round(_percentile(nearest_distances, 0.5), 1),
        "nearest_corridor_distance_p95_m": round(_percentile(nearest_distances, 0.95), 1),
        "nearest_corridor_distance_max_m": round(max(nearest_distances), 1),
        "sensor_availability": {
            "gps_records": len(valid_locations),
            "imu_records": _field_count(records, "motionYaw"),
            "heart_rate_records": _field_count(records, "heartRateBPM"),
            "battery_records": _field_count(records, "batteryLevel"),
            "pedometer_distance_records": _field_count(records, "pedometerDistance"),
            "pedometer_steps_records": _field_count(records, "pedometerNumberOfSteps"),
        },
        "horizontal_accuracy_distribution_m": {
            "p50": round(_percentile(hacc, 0.5), 2),
            "p75": round(_percentile(hacc, 0.75), 2),
            "p90": round(_percentile(hacc, 0.9), 2),
            "p95": round(_percentile(hacc, 0.95), 2),
            "max": round(max(hacc), 2),
            "lte_5_count": sum(1 for value in hacc if value <= 5),
            "lte_10_count": sum(1 for value in hacc if value <= 10),
            "lte_20_count": sum(1 for value in hacc if value <= 20),
            "lte_50_count": sum(1 for value in hacc if value <= 50),
            "gt_50_count": sum(1 for value in hacc if value > 50),
        },
        "elevation_profile_m": {
            "min": round(min(altitude), 1),
            "max": round(max(altitude), 1),
            "gain": round(_positive_gain(altitude), 1),
            "loss": round(_positive_gain([-value for value in altitude]), 1),
        },
        "speed_profile_mps": {
            "median": round(statistics.median(speeds), 2),
            "p90": round(_percentile(speeds, 0.9), 2),
            "max": round(max(speeds), 2),
        },
        "course_available_pct": round(len(course) / len(records), 3),
        "activity_counts": dict(activity_counts),
        "map_coverage": {
            "sample_stride": sample_stride,
            "inside_corridor_count": inside_count,
            "inside_corridor_with_hacc_count": inside_with_hacc_count,
            "nearest_corridor_distance_p50_m": round(_percentile(nearest_distances, 0.5), 1),
            "nearest_corridor_distance_p95_m": round(_percentile(nearest_distances, 0.95), 1),
            "nearest_corridor_distance_max_m": round(max(nearest_distances), 1),
        },
        "representative_samples": representatives,
    }
    return metrics


def _load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("imu_data") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError(f"SensorLog payload must be a list or imu_data object: {path}")
    return [record for record in records if isinstance(record, dict)]


def _map_context_summary(context: Any) -> dict[str, Any]:
    levels = Counter(corridor.route_level for corridor in context.corridors)
    return {
        "source": context.source_metadata.source,
        "source_version": context.source_metadata.source_version,
        "confidence": context.source_metadata.confidence,
        "known_staleness_risk": context.source_metadata.known_staleness_risk,
        "corridors": len(context.corridors),
        "pois": len(context.pois),
        "hazards": len(context.hazards),
        "route_level_counts": dict(sorted(levels.items())),
    }


def _gap_between_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    first_end = _parse_time(segments[0]["end_time"])
    second_start = _parse_time(segments[1]["start_time"])
    first_last = segments[0]["representative_samples"][-1]
    second_first = segments[1]["representative_samples"][0]
    return {
        "duration_s": round((second_start - first_end).total_seconds(), 1),
        "endpoint_distance_m": round(
            haversine_m(first_last["lat"], first_last["lon"], second_first["lat"], second_first["lon"]),
            1,
        ),
    }


def _representative_samples(records: list[dict[str, Any]], map_context: Any, count: int) -> list[dict[str, Any]]:
    if count <= 1:
        selected = [records[0]]
    else:
        selected = [records[round(index * (len(records) - 1) / (count - 1))] for index in range(count)]
    return [_map_sample(record, map_context, include_time=True) for record in selected]


def _map_sample(record: dict[str, Any], map_context: Any, *, include_time: bool = False) -> dict[str, Any] | None:
    location = _lat_lon(record)
    if location is None:
        return None
    lat, lon = location
    hacc = _to_float(record.get("locationHorizontalAccuracy")) or 0.0
    corridor = map_context.corridor_evidence(lat, lon)
    payload = {
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "horizontal_accuracy_m": round(hacc, 2),
        "nearest_corridor_id": corridor.corridor_id,
        "nearest_corridor_distance_m": round(corridor.distance_m, 1),
        "inside_corridor": corridor.inside,
        "inside_corridor_with_hacc": corridor.distance_m <= corridor.allowed_distance_m + hacc,
    }
    if include_time:
        payload["timestamp"] = record.get("loggingTime")
        payload["pedometer_distance_m"] = _round_optional(_to_float(record.get("pedometerDistance")), 1)
    return payload


def _record_time(record: dict[str, Any]) -> datetime:
    return _parse_time(str(record.get("loggingTime")))


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lat_lon(record: dict[str, Any]) -> tuple[float, float] | None:
    lat = _to_float(record.get("locationLatitude"))
    lon = _to_float(record.get("locationLongitude"))
    if lat is None or lon is None:
        return None
    return lat, lon


def _to_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_values(records: list[dict[str, Any]], key: str) -> list[float]:
    return [value for record in records if (value := _to_float(record.get(key))) is not None]


def _field_count(records: list[dict[str, Any]], key: str) -> int:
    return sum(1 for record in records if record.get(key) not in (None, "", "null"))


def _polyline_distance(records: list[dict[str, Any]]) -> float:
    return sum(_record_distance(previous, current) for previous, current in zip(records, records[1:]))


def _record_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_lat, a_lon = _lat_lon(a) or (0.0, 0.0)
    b_lat, b_lon = _lat_lon(b) or (0.0, 0.0)
    return haversine_m(a_lat, a_lon, b_lat, b_lon)


def _delta(values: list[float]) -> float:
    return values[-1] - values[0] if values else 0.0


def _positive_gain(values: list[float]) -> float:
    return sum(max(0.0, current - previous) for previous, current in zip(values, values[1:]))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = percentile * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _round_optional(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


if __name__ == "__main__":
    main()
