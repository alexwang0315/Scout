from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scout_risk.geo import wgs84_to_twd97


@dataclass(frozen=True)
class RiskScorePoint:
    x: float
    y: float
    lon: float
    lat: float
    rs: float
    score_field: str
    route_id: str
    sample_id: str
    distance_m: float | None
    risk_level: int | None
    elevation_m: float | None
    teii_20m: float | None
    tri: float | None
    sri: float | None
    lec: float | None
    scp: float | None
    route_base_source: str | None
    route_base_feature_id: str | None
    route_base_projection_distance_m: float | None
    source_sample_count: int
    source_sample_ids: tuple[str, ...]


@dataclass(frozen=True)
class RiskScorePointMap:
    points: list[RiskScorePoint]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RiskRibbonMap:
    features: list[dict[str, Any]]
    metadata: dict[str, Any]


def build_risk_score_point_map_from_geojson(
    route_risk_geojson_path: str | Path,
    *,
    score_field: str = "pretrip_risk",
    snap_grid_m: float = 20.0,
) -> RiskScorePointMap:
    if snap_grid_m <= 0:
        raise ValueError("snap_grid_m must be positive")

    source_path = Path(route_risk_geojson_path)
    raw = source_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    features = payload.get("features", [])
    cells: dict[tuple[float, float], dict[str, Any]] = {}
    skipped_feature_count = 0

    for feature in features:
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "Point":
            skipped_feature_count += 1
            continue
        coords = geometry.get("coordinates", [])
        if len(coords) < 2:
            skipped_feature_count += 1
            continue
        properties = feature.get("properties", {})
        if score_field not in properties:
            raise ValueError(f"route risk feature missing score field: {score_field}")
        lon = float(coords[0])
        lat = float(coords[1])
        x, y = wgs84_to_twd97(lat, lon)
        grid_x = _snap_to_grid(x, snap_grid_m)
        grid_y = _snap_to_grid(y, snap_grid_m)
        score = float(properties[score_field])
        key = (grid_x, grid_y)
        sample_id = str(properties.get("sample_id", ""))
        current = cells.get(key)
        if current is None:
            cells[key] = {
                "representative": _point_payload(
                    properties,
                    lat=lat,
                    lon=lon,
                    x=grid_x,
                    y=grid_y,
                    rs=score,
                    score_field=score_field,
                ),
                "source_sample_ids": [sample_id],
            }
            continue
        current["source_sample_ids"].append(sample_id)
        if score > current["representative"].rs:
            current["representative"] = _point_payload(
                properties,
                lat=lat,
                lon=lon,
                x=grid_x,
                y=grid_y,
                rs=score,
                score_field=score_field,
            )

    points: list[RiskScorePoint] = []
    for cell in cells.values():
        representative = cell["representative"]
        source_sample_ids = tuple(
            sample_id for sample_id in cell["source_sample_ids"] if sample_id
        )
        points.append(
            RiskScorePoint(
                **{
                    **representative.__dict__,
                    "source_sample_count": len(cell["source_sample_ids"]),
                    "source_sample_ids": source_sample_ids,
                }
            )
        )
    points.sort(key=lambda point: (point.route_id, point.distance_m or 0.0, point.x, point.y))
    metadata = {
        "artifact_kind": "scout_risk_score_point_map",
        "score_surface_type": "route_aligned_point_grid",
        "source_route_risk_ref": str(source_path),
        "source_route_risk_sha256": hashlib.sha256(raw).hexdigest(),
        "score_field": score_field,
        "snap_grid_m": snap_grid_m,
        "aggregation": "max_score_per_twd97_grid_cell",
        "source_feature_count": len(features),
        "skipped_feature_count": skipped_feature_count,
        "point_count": len(points),
        "crs": {
            "xy": "EPSG:3826",
            "geometry": "EPSG:4326",
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "interpolated_surface": False,
            "route_aligned_samples_only": True,
        },
    }
    return RiskScorePointMap(points=points, metadata=metadata)


def build_risk_ribbon_from_geojson(
    route_risk_geojson_path: str | Path,
    *,
    score_field: str = "pretrip_risk",
    max_route_base_segment_m: float = 80.0,
) -> RiskRibbonMap:
    source_path = Path(route_risk_geojson_path)
    raw = source_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    samples = _route_risk_samples(payload, score_field=score_field)
    features: list[dict[str, Any]] = []
    skipped_pair_count = 0

    for start, end in zip(samples, samples[1:]):
        if start["route_id"] != end["route_id"]:
            skipped_pair_count += 1
            continue
        if not _risk_samples_can_connect(
            start,
            end,
            max_route_base_segment_m=max_route_base_segment_m,
        ):
            skipped_pair_count += 1
            continue
        rs = max(float(start["rs"]), float(end["rs"]))
        level = max(
            _optional_int(start.get("risk_level")) or 1,
            _optional_int(end.get("risk_level")) or 1,
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [start["lon"], start["lat"]],
                        [end["lon"], end["lat"]],
                    ],
                },
                "properties": {
                    "segment_id": (
                        f"risk_ribbon.{start['sample_id']}.{end['sample_id']}"
                    ),
                    "route_id": start["route_id"],
                    "from_sample_id": start["sample_id"],
                    "to_sample_id": end["sample_id"],
                    "start_distance_m": start["distance_m"],
                    "end_distance_m": end["distance_m"],
                    "rs": round(rs, 2),
                    "score_field": score_field,
                    "risk_level": level,
                    "risk_bucket": _risk_bucket(rs),
                    "style_class": f"risk-ribbon-{_risk_bucket(rs)}",
                    "stroke": _risk_color(rs),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "interpolated_surface": False,
                    "route_aligned_samples_only": True,
                },
            }
        )

    metadata = {
        "artifact_kind": "scout_risk_route_ribbon",
        "score_surface_type": "route_aligned_risk_ribbon",
        "source_route_risk_ref": str(source_path),
        "source_route_risk_sha256": hashlib.sha256(raw).hexdigest(),
        "score_field": score_field,
        "source_sample_count": len(samples),
        "segment_count": len(features),
        "skipped_pair_count": skipped_pair_count,
        "max_route_base_segment_m": max_route_base_segment_m,
        "style": {
            "low": {"max_exclusive": 40, "stroke": "#8fb7a1"},
            "moderate": {"min": 40, "max_exclusive": 60, "stroke": "#eab308"},
            "high": {"min": 60, "max_exclusive": 80, "stroke": "#f97316"},
            "extreme": {"min": 80, "stroke": "#dc2626"},
        },
        "crs": {
            "geometry": "EPSG:4326",
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "interpolated_surface": False,
            "route_aligned_samples_only": True,
        },
    }
    return RiskRibbonMap(features=features, metadata=metadata)


def write_risk_ribbon_geojson(ribbon: RiskRibbonMap, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": ribbon.metadata,
                "features": ribbon.features,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_risk_ribbon_metadata(ribbon: RiskRibbonMap, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(ribbon.metadata, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_risk_score_csv(point_map: RiskScorePointMap, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "x",
        "y",
        "rs",
        "lat",
        "lon",
        "route_id",
        "sample_id",
        "distance_m",
        "risk_level",
        "score_field",
        "source_sample_count",
        "source_sample_ids",
        "route_base_source",
        "route_base_feature_id",
        "route_base_projection_distance_m",
        "elevation_m",
        "teii_20m",
        "tri",
        "sri",
        "lec",
        "scp",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for point in point_map.points:
            payload = point.__dict__.copy()
            payload["source_sample_ids"] = "|".join(point.source_sample_ids)
            writer.writerow({field: payload.get(field) for field in fields})


def write_risk_score_xyz(point_map: RiskScorePointMap, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for point in point_map.points:
            handle.write(f"{point.x:.3f} {point.y:.3f} {point.rs:.2f}\n")


def write_risk_score_geojson(point_map: RiskScorePointMap, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [point.lon, point.lat]},
            "properties": {
                "x": point.x,
                "y": point.y,
                "rs": point.rs,
                "score_field": point.score_field,
                "route_id": point.route_id,
                "sample_id": point.sample_id,
                "distance_m": point.distance_m,
                "risk_level": point.risk_level,
                "source_sample_count": point.source_sample_count,
                "source_sample_ids": list(point.source_sample_ids),
                "route_base_source": point.route_base_source,
                "route_base_feature_id": point.route_base_feature_id,
                "route_base_projection_distance_m": point.route_base_projection_distance_m,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        }
        for point in point_map.points
    ]
    destination.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": point_map.metadata,
                "features": features,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_risk_score_metadata(point_map: RiskScorePointMap, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(point_map.metadata, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _point_payload(
    properties: dict[str, Any],
    *,
    lat: float,
    lon: float,
    x: float,
    y: float,
    rs: float,
    score_field: str,
) -> RiskScorePoint:
    return RiskScorePoint(
        x=round(x, 3),
        y=round(y, 3),
        lon=lon,
        lat=lat,
        rs=round(rs, 2),
        score_field=score_field,
        route_id=str(properties.get("route_id", "")),
        sample_id=str(properties.get("sample_id", "")),
        distance_m=_optional_float(properties.get("distance_m")),
        risk_level=_optional_int(properties.get("risk_level")),
        elevation_m=_optional_float(properties.get("elevation_m")),
        teii_20m=_optional_float(properties.get("teii_20m")),
        tri=_optional_float(properties.get("tri")),
        sri=_optional_float(properties.get("sri")),
        lec=_optional_float(properties.get("lec")),
        scp=_optional_float(properties.get("scp")),
        route_base_source=_optional_str(properties.get("route_base_source")),
        route_base_feature_id=_optional_str(properties.get("route_base_feature_id")),
        route_base_projection_distance_m=_optional_float(
            properties.get("route_base_projection_distance_m")
        ),
        source_sample_count=1,
        source_sample_ids=(),
    )


def _route_risk_samples(payload: dict[str, Any], *, score_field: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates", [])
        if len(coords) < 2:
            continue
        properties = feature.get("properties", {})
        if score_field not in properties:
            raise ValueError(f"route risk feature missing score field: {score_field}")
        samples.append(
            {
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "rs": float(properties[score_field]),
                "route_id": str(properties.get("route_id", "")),
                "sample_id": str(properties.get("sample_id", "")),
                "distance_m": _optional_float(properties.get("distance_m")),
                "risk_level": _optional_int(properties.get("risk_level")),
                "route_base_source": _optional_str(properties.get("route_base_source")),
                "route_base_feature_id": _optional_str(
                    properties.get("route_base_feature_id")
                ),
                "route_base_projection_distance_m": _optional_float(
                    properties.get("route_base_projection_distance_m")
                ),
            }
        )
    return sorted(
        samples,
        key=lambda sample: (
            sample["route_id"],
            sample["distance_m"] if sample["distance_m"] is not None else 0.0,
        ),
    )


def _risk_samples_can_connect(
    start: dict[str, Any],
    end: dict[str, Any],
    *,
    max_route_base_segment_m: float,
) -> bool:
    start_source = start.get("route_base_source")
    end_source = end.get("route_base_source")
    if start_source is None and end_source is None:
        return True
    if start_source != "overpass_projection" or end_source != "overpass_projection":
        return False
    return (
        _haversine_m(start["lat"], start["lon"], end["lat"], end["lon"])
        <= max_route_base_segment_m
    )


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import atan2, cos, radians, sin, sqrt

    earth_radius_m = 6_371_000.0
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    h = (
        sin(dphi / 2) ** 2
        + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    )
    return earth_radius_m * 2 * atan2(sqrt(h), sqrt(1 - h))


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _risk_bucket(rs: float) -> str:
    if rs >= 80:
        return "extreme"
    if rs >= 60:
        return "high"
    if rs >= 40:
        return "moderate"
    return "low"


def _risk_color(rs: float) -> str:
    if rs >= 80:
        return "#dc2626"
    if rs >= 60:
        return "#f97316"
    if rs >= 40:
        return "#eab308"
    return "#8fb7a1"


def _snap_to_grid(value: float, grid_m: float) -> float:
    return round(value / grid_m) * grid_m


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
