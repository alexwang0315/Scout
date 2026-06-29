from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scout_risk.route.risk_profile import RouteRiskProfile
from scout_risk.route.schemas import RouteRiskSample


def route_profile_to_geojson(profile: RouteRiskProfile) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            _sample_feature(sample)
            for sample in profile.samples
        ],
    }


def write_route_geojson(profile: RouteRiskProfile, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(route_profile_to_geojson(profile), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_route_csv(profile: RouteRiskProfile, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "route_id",
        "sample_id",
        "distance_m",
        "lat",
        "lon",
        "x",
        "y",
        "elevation_m",
        "teii_20m",
        "tri",
        "sri",
        "lec",
        "scp",
        "pretrip_risk",
        "risk_level",
        "route_base_source",
        "route_base_feature_id",
        "route_base_projection_distance_m",
        "hazard_types",
        "explanation",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in profile.samples:
            payload = sample.model_dump(mode="json")
            payload["hazard_types"] = "|".join(sample.hazard_types)
            payload["explanation"] = "|".join(sample.explanation)
            writer.writerow({field: payload.get(field) for field in fields})


def _sample_feature(sample: RouteRiskSample) -> dict[str, Any]:
    lon = sample.lon if sample.lon is not None else sample.x
    lat = sample.lat if sample.lat is not None else sample.y
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": sample.model_dump(
            mode="json",
            exclude={"lat", "lon", "x", "y"},
        ),
    }
