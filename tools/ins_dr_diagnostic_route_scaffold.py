from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_navigation_smoke import load_jsonl_payloads  # noqa: E402


EARTH_RADIUS_M = 6_371_000.0


def build_diagnostic_route_scaffold(
    *,
    output_dir: Path,
    mission_id: str,
    start_lat: float,
    start_lon: float,
    heading_deg: float,
    distance_m: float,
    point_count: int = 5,
    corridor_half_width_m: float = 5.0,
    elevation_m: float | None = None,
) -> dict[str, Any]:
    if not 2 <= point_count <= 100:
        raise ValueError("point_count must be between 2 and 100")
    if not 0.0 <= heading_deg < 360.0:
        raise ValueError("heading_deg must be in [0, 360)")
    if distance_m <= 0:
        raise ValueError("distance_m must be positive")
    if corridor_half_width_m <= 0:
        raise ValueError("corridor_half_width_m must be positive")

    route_points = [
        _destination_point(start_lat, start_lon, heading_deg, distance_m * index / (point_count - 1))
        for index in range(point_count)
    ]
    route_dir = output_dir / "routes"
    mission_dir = output_dir / "mission_graph"
    map_dir = output_dir / "maps"
    route_stem = f"{mission_id}_route"
    route_path = route_dir / f"{route_stem}.gpx"
    mission_path = mission_dir / f"{mission_id}_mission.json"
    map_context_path = map_dir / f"{route_stem}_map_context.geojson"

    _write_text(route_path, _gpx_text(mission_id=mission_id, points=route_points, elevation_m=elevation_m))
    _write_json(
        mission_path,
        _mission_graph(
            mission_id=mission_id,
            route_source=f"../routes/{route_path.name}",
            start_lat=start_lat,
            start_lon=start_lon,
            finish_lat=route_points[-1][0],
            finish_lon=route_points[-1][1],
            distance_m=distance_m,
            elevation_m=elevation_m,
            route_point_end_index=point_count - 1,
        ),
    )
    _write_json(
        map_context_path,
        _map_context(
            mission_id=mission_id,
            route_stem=route_stem,
            route_points=route_points,
            corridor_half_width_m=corridor_half_width_m,
        ),
    )

    return {
        "source": "ins_dr_diagnostic_route_scaffold",
        "artifact_kind": "ins_dr_diagnostic_route_scaffold",
        "mission_id": mission_id,
        "route_gpx": str(route_path),
        "mission_graph_json": str(mission_path),
        "map_context_geojson": str(map_context_path),
        "start": {"lat": start_lat, "lon": start_lon},
        "finish": {"lat": route_points[-1][0], "lon": route_points[-1][1]},
        "heading_deg": heading_deg,
        "distance_m": distance_m,
        "point_count": point_count,
        "corridor_half_width_m": corridor_half_width_m,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_route_scaffold_only",
        "primary_truth_allowed": False,
        "primary_truth_scope": "diagnostic_route_fixture_only",
    }


def start_position_from_gnss_jsonl(path: Path) -> tuple[float, float]:
    for payload in load_jsonl_payloads([path]):
        position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
        fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
        lat = _float_or_none(position.get("lat"))
        lon = _float_or_none(position.get("lon"))
        valid = fix_quality.get("valid")
        if lat is not None and lon is not None and valid is not False:
            return lat, lon
    raise ValueError(f"no valid GNSS position found in {path}")


def _destination_point(lat: float, lon: float, heading_deg: float, distance_m: float) -> tuple[float, float]:
    angular_distance = distance_m / EARTH_RADIUS_M
    bearing = math.radians(heading_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    normalized_lon = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return round(math.degrees(lat2), 8), round(normalized_lon, 8)


def _gpx_text(*, mission_id: str, points: list[tuple[float, float]], elevation_m: float | None) -> str:
    trkpts = []
    for lat, lon in points:
        elevation = f"\n        <ele>{elevation_m:.2f}</ele>" if elevation_m is not None else ""
        trkpts.append(f'      <trkpt lat="{lat:.8f}" lon="{lon:.8f}">{elevation}\n      </trkpt>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="ins_dr_diagnostic_route_scaffold" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <trk><name>{escape(mission_id)}</name><trkseg>\n"
        + "\n".join(trkpts)
        + "\n  </trkseg></trk>\n"
        "</gpx>\n"
    )


def _mission_graph(
    *,
    mission_id: str,
    route_source: str,
    start_lat: float,
    start_lon: float,
    finish_lat: float,
    finish_lon: float,
    distance_m: float,
    elevation_m: float | None,
    route_point_end_index: int,
) -> dict[str, Any]:
    return {
        "mission_id": mission_id,
        "name": f"Diagnostic INS/DR field proof route {mission_id}",
        "route_source": route_source,
        "checkpoints": [
            {
                "checkpoint_id": "cp_start",
                "name": "Diagnostic start",
                "checkpoint_type": "start",
                "lat": start_lat,
                "lon": start_lon,
                "elevation_m": elevation_m,
                "arrival_radius_m": 10.0,
                "compression_boundary": True,
                "must_emit_checkin": True,
                "control_zone_after": "zone_diagnostic_corridor",
                "source": "diagnostic_route_scaffold:start",
            },
            {
                "checkpoint_id": "cp_finish",
                "name": "Diagnostic finish",
                "checkpoint_type": "finish",
                "lat": finish_lat,
                "lon": finish_lon,
                "elevation_m": elevation_m,
                "arrival_radius_m": 10.0,
                "compression_boundary": True,
                "must_emit_checkin": True,
                "control_zone_after": "zone_diagnostic_corridor",
                "source": "diagnostic_route_scaffold:finish",
            },
        ],
        "control_zones": [
            {
                "zone_id": "zone_diagnostic_corridor",
                "zone_type": "unknown",
                "name": "diagnostic corridor",
                "expected_gps_reliability": 0.8,
                "expected_communication_quality": 0.5,
                "slope_risk": 0.0,
                "notes": "Diagnostic-only short route for Scout INS/DR field proof.",
            }
        ],
        "recording_policies": [
            {
                "policy_id": "policy_diagnostic",
                "normal_profile": "low",
                "watch_profile": "medium",
                "concern_profile": "raw_lock",
                "raw_ring_seconds": 180,
                "checkpoint_seals_segment": True,
            }
        ],
        "segments": [
            {
                "segment_id": "seg_diagnostic",
                "from_checkpoint_id": "cp_start",
                "to_checkpoint_id": "cp_finish",
                "control_zone_id": "zone_diagnostic_corridor",
                "recording_policy_id": "policy_diagnostic",
                "requirement": {
                    "min_device_battery": 0.15,
                    "min_estimated_human_energy": 0.2,
                    "expected_duration_seconds": max(1, int(distance_m / 0.5)),
                    "latest_safe_departure_time": None,
                    "requires_daylight": False,
                    "water_available": False,
                    "camp_available": False,
                    "retreat_available": False,
                    "signal_expected": True,
                },
                "distance_m": distance_m,
                "elevation_gain_m": 0.0,
                "elevation_loss_m": 0.0,
                "route_point_start_index": 0,
                "route_point_end_index": route_point_end_index,
            }
        ],
        "diversion_points": [],
    }


def _map_context(
    *,
    mission_id: str,
    route_stem: str,
    route_points: list[tuple[float, float]],
    corridor_half_width_m: float,
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "properties": {
            "source": "diagnostic_ins_dr_route_scaffold",
            "source_version": "v1",
            "confidence": 0.5,
            "last_verified_at": datetime.now(timezone.utc).date().isoformat(),
            "known_staleness_risk": "high",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": f"corridor_{mission_id}",
                    "feature_type": "approved_corridor",
                    "name": f"Diagnostic corridor {mission_id}",
                    "corridor_half_width_m": corridor_half_width_m,
                    "route_level": "diagnostic_field_proof",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lat, lon in route_points],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "id": f"poi_{mission_id}_start",
                    "feature_type": "poi",
                    "poi_type": "diagnostic_start",
                    "name": f"Diagnostic start {route_stem}",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [route_points[0][1], route_points[0][0]],
                },
            },
        ],
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a diagnostic GPX, mission graph, and map corridor for a short Scout INS/DR field proof."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mission-id", default=f"ins_dr_diagnostic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--anchor-jsonl", type=Path)
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--heading-deg", type=float, required=True)
    parser.add_argument("--distance-m", type=float, required=True)
    parser.add_argument("--point-count", type=int, default=5)
    parser.add_argument("--corridor-half-width-m", type=float, default=5.0)
    parser.add_argument("--elevation-m", type=float)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.anchor_jsonl is not None:
            start_lat, start_lon = start_position_from_gnss_jsonl(args.anchor_jsonl)
        elif args.lat is not None and args.lon is not None:
            start_lat, start_lon = args.lat, args.lon
        else:
            raise ValueError("provide --anchor-jsonl or both --lat and --lon")

        report = build_diagnostic_route_scaffold(
            output_dir=args.output_dir,
            mission_id=args.mission_id,
            start_lat=start_lat,
            start_lon=start_lon,
            heading_deg=args.heading_deg,
            distance_m=args.distance_m,
            point_count=args.point_count,
            corridor_half_width_m=args.corridor_half_width_m,
            elevation_m=args.elevation_m,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
