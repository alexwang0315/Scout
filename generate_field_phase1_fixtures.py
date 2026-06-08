from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from generate_field_golden_case import _load_records, _parse_time, _to_float
from geo_utils import haversine_m
from sensorlog_to_gpx import GPX_NS, SCOUT_NS, _add_text, _iso_time, _sanitize_extension_name, _valid_location


MISSION_ID = "scout_260512_field_golden"
FIELD_ROUTE = Path("tests/fixtures/routes/scout_260512_field_route.gpx")
FIELD_ROUTE_085237 = Path("tests/fixtures/routes/scout_260512_085237.gpx")
FIELD_ROUTE_093931 = Path("tests/fixtures/routes/scout_260512_093931.gpx")
MISSION_GRAPH = Path("tests/fixtures/mission_graph/scout_260512_field_mission.json")
MISSION_CONTEXT = Path("tests/fixtures/mission_context/scout_260512_field_normal.json")
RISK_RULES = Path("tests/fixtures/risk_rules/scout_260512_field_rules.json")

EXTENSION_FIELDS = [
    "locationHorizontalAccuracy",
    "locationVerticalAccuracy",
    "locationSpeed",
    "locationCourse",
    "heartRateBPM",
    "heartRateBPS",
    "heartRateVariability",
    "pedometerDistance",
    "pedometerNumberOfSteps",
    "accelerometerAccelerationX",
    "accelerometerAccelerationY",
    "accelerometerAccelerationZ",
    "motionGravityX",
    "motionGravityY",
    "motionGravityZ",
    "motionUserAccelerationX",
    "motionUserAccelerationY",
    "motionUserAccelerationZ",
    "motionRotationRateX",
    "motionRotationRateY",
    "motionRotationRateZ",
    "motionYaw",
    "motionPitch",
    "motionRoll",
    "batteryLevel",
    "batteryState",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Phase 1 fixtures from the Scout 260512 golden case.")
    parser.add_argument(
        "--golden-case",
        default="tests/fixtures/field_cases/scout_260512_golden.json",
        type=Path,
    )
    parser.add_argument("--route-stride", default=10, type=int)
    args = parser.parse_args()

    golden = json.loads(args.golden_case.read_text(encoding="utf-8"))
    source_segments = [
        {
            "id": segment["id"],
            "source_file": Path(segment["source_file"]),
            "records": _load_records(Path(segment["source_file"])),
            "metrics": segment,
        }
        for segment in golden["segments"]
    ]

    selected_segments = [
        {
            **segment,
            "records": _select_records(segment["records"], args.route_stride),
        }
        for segment in source_segments
    ]

    _write_gpx(FIELD_ROUTE_085237, [selected_segments[0]], "Scout 260512 08:52 field route")
    _write_gpx(FIELD_ROUTE_093931, [selected_segments[1]], "Scout 260512 09:39 field route")
    route_index = _write_gpx(FIELD_ROUTE, selected_segments, "Scout 260512 field route")

    checkpoints = _build_checkpoints(golden, route_index)
    graph = _build_mission_graph(golden, checkpoints, route_index)
    MISSION_GRAPH.parent.mkdir(parents=True, exist_ok=True)
    MISSION_GRAPH.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    context = _build_mission_context(golden)
    MISSION_CONTEXT.parent.mkdir(parents=True, exist_ok=True)
    MISSION_CONTEXT.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rules = _build_risk_rules()
    RISK_RULES.parent.mkdir(parents=True, exist_ok=True)
    RISK_RULES.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {FIELD_ROUTE}")
    print(f"Wrote {FIELD_ROUTE_085237}")
    print(f"Wrote {FIELD_ROUTE_093931}")
    print(f"Wrote {MISSION_GRAPH}")
    print(f"Wrote {MISSION_CONTEXT}")
    print(f"Wrote {RISK_RULES}")


def _select_records(records: list[dict[str, Any]], stride: int) -> list[dict[str, Any]]:
    valid = [record for record in records if _valid_location(record, None) is not None]
    selected = valid[::stride]
    if valid[-1] not in selected:
        selected.append(valid[-1])
    return selected


def _write_gpx(path: Path, segments: list[dict[str, Any]], track_name: str) -> list[dict[str, Any]]:
    gpx = ET.Element(
        f"{{{GPX_NS}}}gpx",
        {
            "version": "1.1",
            "creator": "S.C.O.U.T. Fusion generate_field_phase1_fixtures.py",
        },
    )
    metadata = ET.SubElement(gpx, f"{{{GPX_NS}}}metadata")
    _add_text(metadata, f"{{{GPX_NS}}}name", track_name)
    trk = ET.SubElement(gpx, f"{{{GPX_NS}}}trk")
    _add_text(trk, f"{{{GPX_NS}}}name", track_name)

    route_index: list[dict[str, Any]] = []
    global_index = 0
    for segment in segments:
        trkseg = ET.SubElement(trk, f"{{{GPX_NS}}}trkseg")
        for local_index, record in enumerate(segment["records"]):
            location = _valid_location(record, None)
            if location is None:
                continue

            lat, lon = location
            trkpt = ET.SubElement(
                trkseg,
                f"{{{GPX_NS}}}trkpt",
                {"lat": f"{lat:.8f}", "lon": f"{lon:.8f}"},
            )
            elevation = _to_float(record.get("locationAltitude"))
            if elevation is not None:
                _add_text(trkpt, f"{{{GPX_NS}}}ele", f"{elevation:.2f}")
            time_value = _iso_time(record)
            if time_value:
                _add_text(trkpt, f"{{{GPX_NS}}}time", time_value)

            extensions = ET.SubElement(trkpt, f"{{{GPX_NS}}}extensions")
            scout_sample = ET.SubElement(extensions, f"{{{SCOUT_NS}}}sample")
            for key in EXTENSION_FIELDS:
                value = record.get(key)
                if value in (None, "", "null"):
                    continue
                _add_text(scout_sample, f"{{{SCOUT_NS}}}{_sanitize_extension_name(key)}", value)

            route_index.append(
                {
                    "index": global_index,
                    "segment_id": segment["id"],
                    "local_index": local_index,
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": elevation,
                    "timestamp": record.get("loggingTime"),
                }
            )
            global_index += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(gpx)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return route_index


def _build_checkpoints(golden: dict[str, Any], route_index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    picked: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    for segment in golden["segments"]:
        samples = segment["representative_samples"]
        sample_indices = _sample_indices(len(samples), 5)
        for sample_index in sample_indices:
            sample = samples[sample_index]
            picked.append((segment, sample, sample_index))

    checkpoints = []
    total = len(picked)
    for ordinal, (segment, sample, sample_index) in enumerate(picked, start=1):
        nearest_index = _nearest_route_index(sample, route_index)
        checkpoint_type = "terrain_transition"
        name = f"Field checkpoint {ordinal:02d}"
        must_emit = False
        if ordinal == 1:
            checkpoint_type = "start"
            name = "Field start"
            must_emit = True
        elif ordinal == total:
            checkpoint_type = "finish"
            name = "Field finish"
            must_emit = True
        elif ordinal == 5:
            checkpoint_type = "retreat_point"
            name = "Segment 1 end / retreat"
            must_emit = True
        elif ordinal == 6:
            checkpoint_type = "trailhead"
            name = "Segment 2 restart"
            must_emit = True
        elif segment["id"] == "watch_260512_093931" and sample.get("horizontal_accuracy_m", 0) >= 20:
            checkpoint_type = "signal_spot"
            name = f"Weak GPS anchor {ordinal:02d}"
            must_emit = True

        checkpoints.append(
            {
                "checkpoint_id": f"cp_{ordinal:02d}",
                "name": name,
                "checkpoint_type": checkpoint_type,
                "lat": sample["lat"],
                "lon": sample["lon"],
                "elevation_m": _nearest_elevation(sample, route_index),
                "arrival_radius_m": 35.0 if checkpoint_type in {"signal_spot", "trailhead"} else 30.0,
                "compression_boundary": True,
                "must_emit_checkin": must_emit,
                "control_zone_after": _zone_after(ordinal, total),
                "source": f"{segment['id']}:representative_samples[{sample_index}] -> {FIELD_ROUTE.name}:trkpt[{nearest_index}]",
            }
        )
    return checkpoints


def _build_mission_graph(
    golden: dict[str, Any],
    checkpoints: list[dict[str, Any]],
    route_index: list[dict[str, Any]],
) -> dict[str, Any]:
    route_lookup = {point["index"]: point for point in route_index}
    control_zones = [
        _control_zone("zone_field_approach", "trailhead", 0.72, 0.55, 0.15, "Field route approach near mapped trail network."),
        _control_zone("zone_field_forest", "forest", 0.62, 0.38, 0.28, "Mapped forest trail corridor; map evidence is advisory."),
        _control_zone("zone_transfer_gap", "retreat_corridor", 0.8, 0.55, 0.1, "Observed break between two Watch recordings, not continuous walking evidence."),
        _control_zone("zone_weak_gps_forest", "forest", 0.45, 0.32, 0.35, "Second segment preserves weaker GPS for PDR fallback validation."),
        _control_zone("zone_finish_approach", "finish_approach", 0.7, 0.5, 0.18, "Final mapped corridor approach."),
    ]
    recording_policies = [
        {
            "policy_id": "policy_field_low",
            "normal_profile": "low",
            "watch_profile": "medium",
            "concern_profile": "raw_lock",
            "raw_ring_seconds": 180,
            "checkpoint_seals_segment": True,
        },
        {
            "policy_id": "policy_field_medium",
            "normal_profile": "medium",
            "watch_profile": "high",
            "concern_profile": "raw_lock",
            "raw_ring_seconds": 300,
            "checkpoint_seals_segment": True,
        },
        {
            "policy_id": "policy_field_weak_gps",
            "normal_profile": "high",
            "watch_profile": "high",
            "concern_profile": "raw_lock",
            "raw_ring_seconds": 480,
            "checkpoint_seals_segment": True,
        },
    ]

    segments = []
    for index, (start, end) in enumerate(zip(checkpoints, checkpoints[1:]), start=1):
        start_index = _source_route_index(start)
        end_index = _source_route_index(end)
        start_point = route_lookup[start_index]
        end_point = route_lookup[end_index]
        distance_m = _distance_between_route_indices(route_index, start_index, end_index)
        elevation_gain, elevation_loss = _elevation_delta(route_index, start_index, end_index)
        zone_id = start["control_zone_after"] or "zone_field_forest"
        segments.append(
            {
                "segment_id": f"seg_{index:02d}",
                "from_checkpoint_id": start["checkpoint_id"],
                "to_checkpoint_id": end["checkpoint_id"],
                "control_zone_id": zone_id,
                "recording_policy_id": _policy_for_zone(zone_id),
                "requirement": {
                    "min_device_battery": 0.2 if zone_id == "zone_weak_gps_forest" else 0.15,
                    "min_estimated_human_energy": 0.35,
                    "expected_duration_seconds": _expected_duration_seconds(start_point, end_point, distance_m),
                    "latest_safe_departure_time": None,
                    "requires_daylight": zone_id in {"zone_weak_gps_forest", "zone_field_forest"},
                    "water_available": False,
                    "camp_available": False,
                    "retreat_available": zone_id == "zone_transfer_gap" or end["checkpoint_type"] == "retreat_point",
                    "signal_expected": zone_id not in {"zone_field_forest", "zone_weak_gps_forest"},
                },
                "distance_m": round(distance_m, 2),
                "elevation_gain_m": round(elevation_gain, 2),
                "elevation_loss_m": round(elevation_loss, 2),
                "route_point_start_index": start_index,
                "route_point_end_index": end_index,
            }
        )

    return {
        "mission_id": MISSION_ID,
        "name": "Scout 2026-05-12 field golden mission",
        "route_source": str(FIELD_ROUTE),
        "checkpoints": checkpoints,
        "control_zones": control_zones,
        "recording_policies": recording_policies,
        "segments": segments,
        "diversion_points": [
            {
                "diversion_id": "div_return_first_segment_start",
                "name": "Return to first field start",
                "diversion_type": "retreat",
                "lat": checkpoints[0]["lat"],
                "lon": checkpoints[0]["lon"],
                "distance_from_route_m": 0.0,
                "required_energy": 0.2,
                "required_daylight_seconds": 1200,
                "communication_available": True,
                "risk_level": 0.25,
            },
            {
                "diversion_id": "div_restart_segment_two",
                "name": "Hold at second segment restart",
                "diversion_type": "hold",
                "lat": checkpoints[5]["lat"],
                "lon": checkpoints[5]["lon"],
                "distance_from_route_m": 0.0,
                "required_energy": 0.1,
                "required_daylight_seconds": 600,
                "communication_available": True,
                "risk_level": 0.2,
            },
        ],
    }


def _build_mission_context(golden: dict[str, Any]) -> dict[str, Any]:
    first, second = golden["segments"]
    return {
        "resource_state": {
            "device_battery": second["battery_end"],
            "estimated_human_energy": 0.78,
            "pace_trend": 0.9,
            "heart_rate_trend": "stable",
            "fatigue_score": 0.18,
        },
        "environment_state": {
            "weather_risk": 0.12,
            "temperature_c": 25.0,
            "rain_probability": 0.1,
            "wind_speed_mps": 2.0,
            "sunset_time": "2026-05-12T18:31:00+08:00",
            "daylight_remaining_seconds": 30000,
            "visibility": "good",
        },
        "communication_state": {
            "capabilities": [
                {
                    "channel": "cellular",
                    "available": True,
                    "signal_strength": None,
                    "supports_outbound": True,
                    "supports_inbound": True,
                    "supports_nearby_pull": False,
                    "estimated_delivery_confidence": 0.62,
                },
                {
                    "channel": "bluetooth",
                    "available": True,
                    "signal_strength": None,
                    "supports_outbound": False,
                    "supports_inbound": True,
                    "supports_nearby_pull": True,
                    "estimated_delivery_confidence": 0.55,
                },
            ],
            "last_successful_uplink": first["start_time"],
        },
        "route_context": {
            "mission_id": MISSION_ID,
            "current_segment_id": "seg_01",
            "control_zone_id": "zone_field_approach",
            "matched_route_confidence": min(first["map_inside_corridor_with_hacc_pct"], second["map_inside_corridor_with_hacc_pct"]),
            "map_context": golden["map_context"],
            "golden_case": "tests/fixtures/field_cases/scout_260512_golden.json",
        },
    }


def _build_risk_rules() -> dict[str, Any]:
    return {
        "ruleset_id": "scout_260512_field_phase1_rules",
        "mission_id": MISSION_ID,
        "source": "golden_case_fixture",
        "source_version": "scout-260512-field-golden",
        "rules": [
            {
                "rule_id": "field_dense_bamboo_cliff_l2",
                "name": "Field dense bamboo near cliff exposure",
                "hazard_types": ["dense_bamboo", "cliff_exposure"],
                "hazard_match": "all",
                "min_duration_s": 30.0,
                "min_map_confidence": 0.6,
                "requires_weak_gps": None,
                "segment_ids": [],
                "output_level": "L2_CONCERN",
                "confidence": 0.86,
                "reason": "Field mission treats sustained dense bamboo plus cliff exposure as concern-level risk.",
            },
            {
                "rule_id": "field_steep_slope_weak_gps_l2",
                "name": "Field steep slope with weak GPS",
                "hazard_types": ["steep_slope"],
                "hazard_match": "any",
                "min_duration_s": 30.0,
                "min_map_confidence": 0.65,
                "requires_weak_gps": True,
                "segment_ids": ["seg_06", "seg_07", "seg_08"],
                "output_level": "L2_CONCERN",
                "confidence": 0.84,
                "reason": "Weak GPS on field forest segments raises route-loss risk when map hazards indicate steep slope.",
            },
            {
                "rule_id": "field_low_confidence_hazard_watch",
                "name": "Field low-confidence hazard watch",
                "hazard_types": ["steep_slope", "river", "landslide", "dense_bamboo", "cliff_exposure"],
                "hazard_match": "any",
                "min_duration_s": 30.0,
                "min_map_confidence": 0.3,
                "requires_weak_gps": None,
                "segment_ids": [],
                "output_level": "L1_WATCH",
                "confidence": 0.6,
                "reason": "Sustained lower-confidence map hazard evidence should raise watch level before L2 escalation.",
            },
        ],
    }


def _sample_indices(length: int, count: int) -> list[int]:
    return sorted({round(index * (length - 1) / (count - 1)) for index in range(count)})


def _nearest_route_index(sample: dict[str, Any], route_index: list[dict[str, Any]]) -> int:
    best = min(route_index, key=lambda point: haversine_m(sample["lat"], sample["lon"], point["lat"], point["lon"]))
    return int(best["index"])


def _nearest_elevation(sample: dict[str, Any], route_index: list[dict[str, Any]]) -> float | None:
    best = min(route_index, key=lambda point: haversine_m(sample["lat"], sample["lon"], point["lat"], point["lon"]))
    value = best.get("elevation_m")
    return round(value, 2) if value is not None else None


def _zone_after(ordinal: int, total: int) -> str:
    if ordinal == 1:
        return "zone_field_approach"
    if ordinal == 5:
        return "zone_transfer_gap"
    if ordinal >= 6 and ordinal < total:
        return "zone_weak_gps_forest"
    if ordinal == total:
        return "zone_finish_approach"
    return "zone_field_forest"


def _control_zone(
    zone_id: str,
    zone_type: str,
    gps_reliability: float,
    communication_quality: float,
    slope_risk: float,
    notes: str,
) -> dict[str, Any]:
    return {
        "zone_id": zone_id,
        "zone_type": zone_type,
        "name": zone_id.removeprefix("zone_").replace("_", " "),
        "expected_gps_reliability": gps_reliability,
        "expected_communication_quality": communication_quality,
        "slope_risk": slope_risk,
        "notes": notes,
    }


def _policy_for_zone(zone_id: str) -> str:
    if zone_id == "zone_weak_gps_forest":
        return "policy_field_weak_gps"
    if zone_id in {"zone_field_forest", "zone_transfer_gap"}:
        return "policy_field_medium"
    return "policy_field_low"


def _source_route_index(checkpoint: dict[str, Any]) -> int:
    source = checkpoint["source"]
    return int(source.rsplit("trkpt[", 1)[1].rstrip("]"))


def _distance_between_route_indices(route_index: list[dict[str, Any]], start: int, end: int) -> float:
    selected = route_index[min(start, end) : max(start, end) + 1]
    return sum(
        haversine_m(previous["lat"], previous["lon"], current["lat"], current["lon"])
        for previous, current in zip(selected, selected[1:])
    )


def _elevation_delta(route_index: list[dict[str, Any]], start: int, end: int) -> tuple[float, float]:
    selected = route_index[min(start, end) : max(start, end) + 1]
    values = [point["elevation_m"] for point in selected if point.get("elevation_m") is not None]
    gain = 0.0
    loss = 0.0
    for previous, current in zip(values, values[1:]):
        delta = current - previous
        if delta >= 0:
            gain += delta
        else:
            loss += abs(delta)
    return gain, loss


def _expected_duration_seconds(start: dict[str, Any], end: dict[str, Any], fallback_distance_m: float) -> int:
    start_time = start.get("timestamp")
    end_time = end.get("timestamp")
    if start_time and end_time:
        seconds = abs((_parse_time(end_time) - _parse_time(start_time)).total_seconds())
        if seconds > 0:
            return int(round(seconds))
    return int(math.ceil(fallback_distance_m / 0.6))


if __name__ == "__main__":
    main()
