#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


GPX_NS = "http://www.topografix.com/GPX/1/1"
ET.register_namespace("", GPX_NS)


def _ns(root: ET.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": GPX_NS}


def _to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _text(element: ET.Element, name: str, ns: dict[str, str], default: str | None = None) -> str | None:
    found = element.find(f"g:{name}", ns)
    return found.text if found is not None else default


def _set_extension_text(element: ET.Element, local_name: str, value: str) -> None:
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1] == local_name:
            child.text = value
            return


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def _track_points(root: ET.Element, ns: dict[str, str]) -> list[ET.Element]:
    return root.findall(".//g:trkpt", ns)


def _checkpoint_indices(point_count: int, target_count: int = 10) -> list[int]:
    if point_count <= 0:
        return []
    if point_count <= target_count:
        return list(range(point_count))
    return sorted({round(i * (point_count - 1) / (target_count - 1)) for i in range(target_count)})


def _checkpoint_type(index: int, total: int, elevation_delta: float, distance_m: float) -> tuple[str, str, str]:
    if index == 0:
        return "start", "urban_edge", "Start"
    if index == total - 1:
        return "finish", "finish_approach", "Finish"
    slope = abs(elevation_delta) / max(distance_m, 1.0)
    if slope >= 0.30:
        return "high_risk_entry", "steep_descent", "Steep terrain gate"
    if elevation_delta > 8:
        return "ridge_entry", "ridge_approach", "Climb transition"
    if elevation_delta < -8:
        return "retreat_point", "retreat_corridor", "Descent / retreat gate"
    return "terrain_transition", "forest", "Route checkpoint"


def _control_zone(zone_id: str, zone_type: str) -> dict:
    return {
        "zone_id": zone_id,
        "zone_type": zone_type,
        "name": zone_type.replace("_", " "),
        "expected_gps_reliability": 0.55 if zone_type in {"forest", "steep_descent"} else 0.8,
        "expected_communication_quality": 0.35 if zone_type in {"forest", "steep_descent"} else 0.65,
        "slope_risk": 0.75 if zone_type in {"steep_descent", "ridge_crossing"} else 0.25,
        "notes": "generated from Apple Watch track geometry",
    }


def build_mission_graph(route_path: Path, output_path: Path) -> dict:
    tree = ET.parse(route_path)
    root = tree.getroot()
    ns = _ns(root)
    points = _track_points(root, ns)
    if not points:
        raise ValueError(f"No GPX track points found: {route_path}")

    indices = _checkpoint_indices(len(points), target_count=10)
    checkpoints: list[dict] = []
    zone_ids: list[tuple[str, str]] = []
    prior_lat_lon: tuple[float, float] | None = None
    prior_ele = 0.0

    for ordinal, point_index in enumerate(indices, start=1):
        point = points[point_index]
        lat = _to_float(point.attrib.get("lat"))
        lon = _to_float(point.attrib.get("lon"))
        ele = _to_float(_text(point, "ele", ns), 0.0)
        lat_lon = (lat, lon)
        distance = _haversine_m(prior_lat_lon, lat_lon) if prior_lat_lon else 0.0
        elevation_delta = ele - prior_ele if prior_lat_lon else 0.0
        cp_type, zone_type, label = _checkpoint_type(ordinal - 1, len(indices), elevation_delta, distance)
        zone_id = f"zone_{zone_type}"
        zone_ids.append((zone_id, zone_type))

        checkpoints.append(
            {
                "checkpoint_id": f"cp_{ordinal:02d}",
                "name": f"{label} {ordinal:02d}",
                "checkpoint_type": cp_type,
                "lat": lat,
                "lon": lon,
                "elevation_m": ele,
                "arrival_radius_m": 30.0 if cp_type not in {"high_risk_entry", "ridge_entry"} else 40.0,
                "compression_boundary": True,
                "must_emit_checkin": cp_type in {"start", "finish", "ridge_entry", "retreat_point", "high_risk_entry"},
                "control_zone_after": zone_id,
                "source": f"{route_path.name}:trkpt[{point_index}]",
            }
        )
        prior_lat_lon = lat_lon
        prior_ele = ele

    control_zones = [_control_zone(zone_id, zone_type) for zone_id, zone_type in sorted(set(zone_ids))]
    recording_policies = [
        {
            "policy_id": "policy_low",
            "normal_profile": "low",
            "watch_profile": "medium",
            "concern_profile": "raw_lock",
            "raw_ring_seconds": 180,
            "checkpoint_seals_segment": True,
        },
        {
            "policy_id": "policy_medium",
            "normal_profile": "medium",
            "watch_profile": "high",
            "concern_profile": "raw_lock",
            "raw_ring_seconds": 300,
            "checkpoint_seals_segment": True,
        },
        {
            "policy_id": "policy_high_risk",
            "normal_profile": "high",
            "watch_profile": "high",
            "concern_profile": "raw_lock",
            "raw_ring_seconds": 300,
            "checkpoint_seals_segment": True,
        },
    ]

    def policy_for(zone_id: str) -> str:
        if "steep" in zone_id or "ridge" in zone_id:
            return "policy_high_risk"
        if "forest" in zone_id:
            return "policy_medium"
        return "policy_low"

    segments: list[dict] = []
    for index in range(len(checkpoints) - 1):
        start = checkpoints[index]
        end = checkpoints[index + 1]
        distance = _haversine_m((start["lat"], start["lon"]), (end["lat"], end["lon"]))
        gain = max(0.0, end["elevation_m"] - start["elevation_m"])
        loss = max(0.0, start["elevation_m"] - end["elevation_m"])
        zone_id = start["control_zone_after"] or "zone_forest"
        forced_daylight_gate = index == max(1, (len(checkpoints) - 1) // 2)
        high_risk = "steep" in zone_id or "ridge" in zone_id or forced_daylight_gate
        segments.append(
            {
                "segment_id": f"seg_{index + 1:02d}",
                "from_checkpoint_id": start["checkpoint_id"],
                "to_checkpoint_id": end["checkpoint_id"],
                "control_zone_id": zone_id,
                "recording_policy_id": policy_for(zone_id),
                "requirement": {
                    "min_device_battery": 0.25 if high_risk else 0.15,
                    "min_estimated_human_energy": 0.45 if high_risk else 0.30,
                    "expected_duration_seconds": max(120, int(distance / 0.6)),
                    "latest_safe_departure_time": None,
                    "requires_daylight": high_risk,
                    "water_available": False,
                    "camp_available": False,
                    "retreat_available": end["checkpoint_type"] == "retreat_point",
                    "signal_expected": zone_id not in {"zone_forest", "zone_steep_descent"},
                },
                "distance_m": round(distance, 2),
                "elevation_gain_m": round(gain, 2),
                "elevation_loss_m": round(loss, 2),
                "route_point_start_index": indices[index],
                "route_point_end_index": indices[index + 1],
            }
        )

    graph = {
        "mission_id": "apple-watch-260511-0852",
        "name": "Apple Watch 260511 08:52 raw climb",
        "route_source": str(route_path),
        "checkpoints": checkpoints,
        "control_zones": control_zones,
        "recording_policies": recording_policies,
        "segments": segments,
        "diversion_points": [
            {
                "diversion_id": "div_start_return",
                "name": "Return to start",
                "diversion_type": "retreat",
                "lat": checkpoints[0]["lat"],
                "lon": checkpoints[0]["lon"],
                "distance_from_route_m": 0.0,
                "required_energy": 0.15,
                "required_daylight_seconds": 900,
                "communication_available": True,
                "risk_level": 0.2,
            }
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n")
    return graph


def generate_route_variants(route_path: Path, output_dir: Path) -> None:
    tree = ET.parse(route_path)
    root = tree.getroot()
    ns = _ns(root)

    for name in ["off_route_deviation.gpx", "backtracking_loop.gpx", "weak_gps_route.gpx"]:
        variant = copy.deepcopy(tree)
        variant_root = variant.getroot()
        variant_ns = _ns(variant_root)
        points = variant_root.findall(".//g:trkpt", variant_ns)
        if not points:
            raise ValueError("No points in route variant source")

        if name == "off_route_deviation.gpx":
            start = len(points) // 2 - 80
            end = len(points) // 2 + 80
            for point in points[start:end]:
                point.set("lat", f"{_to_float(point.attrib.get('lat')) + 0.0030:.8f}")
                point.set("lon", f"{_to_float(point.attrib.get('lon')) + 0.0030:.8f}")
        elif name == "backtracking_loop.gpx":
            segment = variant_root.find(".//g:trkseg", variant_ns)
            if segment is None:
                raise ValueError("No trkseg in route variant source")
            start = len(points) // 3
            loop = points[start : start + 220]
            insert_at = start + 220
            for item in list(reversed(loop)) + loop:
                segment.insert(insert_at, copy.deepcopy(item))
                insert_at += 1
        else:
            segment = variant_root.find(".//g:trkseg", variant_ns)
            if segment is None:
                raise ValueError("No trkseg in route variant source")
            start = len(points) // 2 - 250
            end = len(points) // 2 + 250
            for point in points[start:end]:
                _set_extension_text(point, "locationHorizontalAccuracy", "185.000000")
                _set_extension_text(point, "locationVerticalAccuracy", "220.000000")
            for index, point in enumerate(list(segment)):
                if point.tag.endswith("trkpt") and index % 5 not in (0, 1):
                    segment.remove(point)

        track_name = variant_root.find(".//g:trk/g:name", variant_ns)
        if track_name is not None:
            track_name.text = name.removesuffix(".gpx").replace("_", " ")
        variant.write(output_dir / name, encoding="utf-8", xml_declaration=True)


def write_context_fixtures(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    contexts = {
        "normal.json": {
            "resource_state": {"device_battery": 0.82, "estimated_human_energy": 0.86, "pace_trend": 1.0, "heart_rate_trend": "stable", "fatigue_score": 0.1},
            "environment_state": {"weather_risk": 0.1, "temperature_c": 23.0, "rain_probability": 0.1, "wind_speed_mps": 2.0, "sunset_time": "2026-05-11T10:30:00Z", "daylight_remaining_seconds": 7200, "visibility": "good"},
            "communication_state": {"capabilities": [{"channel": "cellular", "available": True, "signal_strength": -82, "supports_outbound": True, "supports_inbound": True, "supports_nearby_pull": False, "estimated_delivery_confidence": 0.75}, {"channel": "bluetooth", "available": True, "supports_outbound": False, "supports_inbound": True, "supports_nearby_pull": True, "estimated_delivery_confidence": 0.65}], "last_successful_uplink": "2026-05-11T00:52:12Z"},
            "route_context": {"mission_id": "apple-watch-260511-0852", "current_segment_id": "seg_01", "matched_route_confidence": 0.9},
        },
        "low_battery_near_sunset.json": {
            "resource_state": {"device_battery": 0.14, "estimated_human_energy": 0.32, "pace_trend": 0.62, "heart_rate_trend": "elevated", "fatigue_score": 0.58},
            "environment_state": {"weather_risk": 0.25, "temperature_c": 20.0, "rain_probability": 0.2, "wind_speed_mps": 3.0, "sunset_time": "2026-05-11T10:30:00Z", "daylight_remaining_seconds": 1500, "visibility": "fair"},
            "communication_state": {"capabilities": [{"channel": "cellular", "available": True, "signal_strength": -101, "supports_outbound": True, "supports_inbound": True, "supports_nearby_pull": False, "estimated_delivery_confidence": 0.35}], "last_successful_uplink": "2026-05-11T01:00:00Z"},
            "route_context": {"mission_id": "apple-watch-260511-0852", "current_segment_id": "seg_05", "matched_route_confidence": 0.7},
        },
        "no_signal_high_risk_zone.json": {
            "resource_state": {"device_battery": 0.48, "estimated_human_energy": 0.55, "pace_trend": 0.78, "heart_rate_trend": "elevated", "fatigue_score": 0.35},
            "environment_state": {"weather_risk": 0.35, "temperature_c": 21.0, "rain_probability": 0.35, "wind_speed_mps": 5.0, "sunset_time": "2026-05-11T10:30:00Z", "daylight_remaining_seconds": 3600, "visibility": "fair"},
            "communication_state": {"capabilities": [{"channel": "cellular", "available": False, "supports_outbound": False, "supports_inbound": False, "supports_nearby_pull": False, "estimated_delivery_confidence": 0.0}, {"channel": "bluetooth", "available": True, "supports_outbound": False, "supports_inbound": True, "supports_nearby_pull": True, "estimated_delivery_confidence": 0.45}], "last_successful_uplink": "2026-05-11T00:59:00Z"},
            "route_context": {"mission_id": "apple-watch-260511-0852", "current_segment_id": "seg_06", "matched_route_confidence": 0.62, "control_zone_id": "zone_steep_descent"},
        },
        "weather_deteriorating.json": {
            "resource_state": {"device_battery": 0.66, "estimated_human_energy": 0.72, "pace_trend": 0.9, "heart_rate_trend": "stable", "fatigue_score": 0.2},
            "environment_state": {"weather_risk": 0.72, "temperature_c": 18.0, "rain_probability": 0.8, "wind_speed_mps": 9.0, "sunset_time": "2026-05-11T10:30:00Z", "daylight_remaining_seconds": 4200, "visibility": "poor"},
            "communication_state": {"capabilities": [{"channel": "cellular", "available": True, "signal_strength": -92, "supports_outbound": True, "supports_inbound": True, "supports_nearby_pull": False, "estimated_delivery_confidence": 0.55}], "last_successful_uplink": "2026-05-11T01:01:00Z"},
            "route_context": {"mission_id": "apple-watch-260511-0852", "current_segment_id": "seg_04", "matched_route_confidence": 0.82},
        },
    }
    for name, payload in contexts.items():
        (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Phase 1 route, mission graph, and context fixtures.")
    parser.add_argument("--route", type=Path, default=Path("tests/fixtures/routes/normal_climb.gpx"))
    parser.add_argument("--routes-dir", type=Path, default=Path("tests/fixtures/routes"))
    parser.add_argument("--mission-output", type=Path, default=Path("tests/fixtures/mission_graph/normal_climb_mission.json"))
    parser.add_argument("--context-dir", type=Path, default=Path("tests/fixtures/mission_context"))
    args = parser.parse_args()

    graph = build_mission_graph(args.route, args.mission_output)
    generate_route_variants(args.route, args.routes_dir)
    write_context_fixtures(args.context_dir)
    print(f"Wrote {len(graph['checkpoints'])} checkpoints and {len(graph['segments'])} segments")


if __name__ == "__main__":
    main()
