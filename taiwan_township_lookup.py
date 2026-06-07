from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from geo_utils import haversine_m


TAIWAN_TOWNSHIP_LOOKUP_KIND = "taiwan_township_lookup_result"
DEFAULT_MAX_DISTANCE_KM = 25.0
DEFAULT_HIGH_CONFIDENCE_KM = 2.0
DEFAULT_MEDIUM_CONFIDENCE_KM = 10.0


def load_township_gazetteer(path: Path | str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = (
            raw.get("townships")
            or raw.get("records")
            or raw.get("items")
            or raw.get("features")
            or []
        )
    else:
        records = []
    return [
        record
        for record in (_normalize_record(item) for item in records)
        if record is not None
    ]


def lookup_township(
    lat: float,
    lon: float,
    *,
    gazetteer_path: Path | str | None = None,
    gazetteer: Iterable[dict[str, Any]] | None = None,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    high_confidence_km: float = DEFAULT_HIGH_CONFIDENCE_KM,
    medium_confidence_km: float = DEFAULT_MEDIUM_CONFIDENCE_KM,
) -> dict[str, Any]:
    records = (
        list(gazetteer)
        if gazetteer is not None
        else load_township_gazetteer(gazetteer_path) if gazetteer_path is not None else []
    )
    normalized = [
        record
        for record in (_normalize_record(item) for item in records)
        if record is not None
    ]
    if not _valid_lat_lon(lat, lon):
        return _missing_result(lat, lon, "invalid_lat_lon", records=normalized)
    if not normalized:
        return _missing_result(lat, lon, "gazetteer_empty", records=normalized)

    candidates = []
    for record in normalized:
        distance_km = haversine_m(lat, lon, record["lat"], record["lon"]) / 1000.0
        bbox_match = _point_in_bbox(lat, lon, record.get("bbox"))
        candidates.append(
            {
                "county": record.get("county"),
                "township": record.get("township"),
                "areaName": record.get("township"),
                "distance_km": round(distance_km, 3),
                "bbox_match": bbox_match,
            }
        )
    ranked = sorted(candidates, key=lambda item: (not item["bbox_match"], item["distance_km"]))
    best = ranked[0]
    method = "bbox_centroid" if best["bbox_match"] else "nearest_centroid"
    if not best["bbox_match"] and float(best["distance_km"]) > max_distance_km:
        result = _missing_result(
            lat,
            lon,
            "nearest_centroid_outside_max_distance",
            records=normalized,
        )
        result["candidates"] = ranked[:3]
        return result

    confidence = _confidence(
        best,
        ranked[1] if len(ranked) > 1 else None,
        high_confidence_km=high_confidence_km,
        medium_confidence_km=medium_confidence_km,
    )
    warnings = []
    if confidence == "low":
        warnings.append(
            "Township lookup is approximate; use polygon/admin-boundary evidence for safety decisions."
        )
    if len(ranked) > 1 and _is_ambiguous(best, ranked[1]):
        warnings.append("Nearest township candidates are close; boundary ambiguity is possible.")

    return {
        "artifact_kind": TAIWAN_TOWNSHIP_LOOKUP_KIND,
        "lat": float(lat),
        "lon": float(lon),
        "matched": True,
        "county": best.get("county"),
        "township": best.get("township"),
        "areaName": best.get("areaName"),
        "distance_km": best["distance_km"],
        "method": method,
        "confidence": confidence,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "coverage": "gazetteer_records_only",
        "warnings": warnings,
        "candidates": ranked[:3],
        "boundary": _boundary(),
    }


def lookup_township_name(
    lat: float,
    lon: float,
    *,
    gazetteer_path: Path | str | None = None,
    gazetteer: Iterable[dict[str, Any]] | None = None,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    min_confidence: str = "low",
) -> str | None:
    result = lookup_township(
        lat,
        lon,
        gazetteer_path=gazetteer_path,
        gazetteer=gazetteer,
        max_distance_km=max_distance_km,
    )
    if not result.get("matched"):
        return None
    allowed = _confidence_rank(result.get("confidence")) >= _confidence_rank(min_confidence)
    if not allowed:
        return None
    return str(result.get("township") or "") or None


def make_township_lookup_callback(
    *,
    gazetteer_path: Path | str | None = None,
    gazetteer: Iterable[dict[str, Any]] | None = None,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    min_confidence: str = "low",
    return_metadata: bool = False,
):
    records = (
        list(gazetteer)
        if gazetteer is not None
        else load_township_gazetteer(gazetteer_path) if gazetteer_path is not None else []
    )

    def _callback(lat: float, lon: float) -> str | dict[str, Any] | None:
        result = lookup_township(
            lat,
            lon,
            gazetteer=records,
            max_distance_km=max_distance_km,
        )
        if not result.get("matched"):
            return result if return_metadata else None
        if _confidence_rank(result.get("confidence")) < _confidence_rank(min_confidence):
            return result if return_metadata else None
        return result if return_metadata else str(result.get("township") or "") or None

    return _callback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Approximate Taiwan lat/lon to township lookup using a centroid/bbox gazetteer."
        )
    )
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--gazetteer", type=Path, required=True)
    parser.add_argument("--max-distance-km", type=float, default=DEFAULT_MAX_DISTANCE_KM)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    result = lookup_township(
        args.lat,
        args.lon,
        gazetteer_path=args.gazetteer,
        max_distance_km=args.max_distance_km,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if result.get("matched") else 2


def _normalize_record(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    source = {**raw, **properties}
    centroid = source.get("centroid") if isinstance(source.get("centroid"), dict) else {}
    geometry_bbox = _geometry_bbox(source.get("geometry"))
    bbox = _normalize_bbox(source.get("bbox") or source.get("bounds")) or geometry_bbox
    lat = _float_or_none(
        source.get("lat")
        or source.get("latitude")
        or source.get("centroid_lat")
        or source.get("centroidLat")
        or centroid.get("lat")
        or centroid.get("latitude")
    )
    lon = _float_or_none(
        source.get("lon")
        or source.get("lng")
        or source.get("longitude")
        or source.get("centroid_lon")
        or source.get("centroidLon")
        or centroid.get("lon")
        or centroid.get("lng")
        or centroid.get("longitude")
    )
    if lat is None and bbox is not None:
        lat = (bbox["min_lat"] + bbox["max_lat"]) / 2.0
    if lon is None and bbox is not None:
        lon = (bbox["min_lon"] + bbox["max_lon"]) / 2.0
    township = _first_text(
        source,
        "township",
        "town",
        "areaName",
        "area_name",
        "locationName",
        "name",
        "TOWNNAME",
        "townname",
    )
    county = _first_text(
        source,
        "county",
        "city",
        "countyName",
        "county_name",
        "COUNTYNAME",
        "countyname",
    )
    if lat is None or lon is None or not township:
        return None
    return {
        "county": county,
        "township": township,
        "lat": lat,
        "lon": lon,
        "bbox": bbox,
    }


def _normalize_bbox(raw: Any) -> dict[str, float] | None:
    if isinstance(raw, dict):
        min_lat = _float_or_none(raw.get("min_lat") or raw.get("south") or raw.get("minLat"))
        max_lat = _float_or_none(raw.get("max_lat") or raw.get("north") or raw.get("maxLat"))
        min_lon = _float_or_none(raw.get("min_lon") or raw.get("west") or raw.get("minLon"))
        max_lon = _float_or_none(raw.get("max_lon") or raw.get("east") or raw.get("maxLon"))
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        first = _float_or_none(raw[0])
        second = _float_or_none(raw[1])
        third = _float_or_none(raw[2])
        fourth = _float_or_none(raw[3])
        if first is not None and third is not None and (abs(first) > 90 or abs(third) > 90):
            min_lon, min_lat, max_lon, max_lat = first, second, third, fourth
        else:
            min_lat, min_lon, max_lat, max_lon = first, second, third, fourth
    else:
        return None
    if None in {min_lat, max_lat, min_lon, max_lon}:
        return None
    return {
        "min_lat": min(min_lat, max_lat),
        "max_lat": max(min_lat, max_lat),
        "min_lon": min(min_lon, max_lon),
        "max_lon": max(min_lon, max_lon),
    }


def _point_in_bbox(lat: float, lon: float, bbox: Any) -> bool:
    if not isinstance(bbox, dict):
        return False
    return (
        bbox["min_lat"] <= lat <= bbox["max_lat"]
        and bbox["min_lon"] <= lon <= bbox["max_lon"]
    )


def _geometry_bbox(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    pairs: list[tuple[float, float]] = []

    def _walk(node: Any) -> None:
        if not isinstance(node, (list, tuple)) or not node:
            return
        lon = _float_or_none(node[0]) if len(node) >= 2 else None
        lat = _float_or_none(node[1]) if len(node) >= 2 else None
        if lon is not None and lat is not None and _valid_lat_lon(lat, lon):
            pairs.append((lat, lon))
            return
        for child in node:
            _walk(child)

    _walk(raw.get("coordinates"))
    if not pairs:
        return None
    lats = [item[0] for item in pairs]
    lons = [item[1] for item in pairs]
    return {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lon": min(lons),
        "max_lon": max(lons),
    }


def _confidence(
    best: dict[str, Any],
    second: dict[str, Any] | None,
    *,
    high_confidence_km: float,
    medium_confidence_km: float,
) -> str:
    if _is_ambiguous(best, second):
        return "low"
    distance = float(best["distance_km"])
    if best["bbox_match"] or distance <= high_confidence_km:
        return "high"
    if distance <= medium_confidence_km:
        return "medium"
    return "low"


def _is_ambiguous(best: dict[str, Any], second: dict[str, Any] | None) -> bool:
    if second is None:
        return False
    if best["bbox_match"] and not second["bbox_match"]:
        return False
    best_distance = float(best["distance_km"])
    second_distance = float(second["distance_km"])
    return abs(second_distance - best_distance) <= 1.0


def _missing_result(
    lat: float,
    lon: float,
    reason: str,
    *,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "artifact_kind": TAIWAN_TOWNSHIP_LOOKUP_KIND,
        "lat": float(lat),
        "lon": float(lon),
        "matched": False,
        "county": None,
        "township": None,
        "areaName": None,
        "distance_km": None,
        "method": "none",
        "confidence": "missing",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "coverage": "gazetteer_records_only",
        "warnings": [reason],
        "candidate_count": len(records),
        "candidates": [],
        "boundary": _boundary(),
    }


def _boundary() -> dict[str, bool]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "replaces_polygon_mapping_for_safety": False,
        "requires_authoritative_boundary_for_safety": True,
    }


def _valid_lat_lon(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _confidence_rank(value: Any) -> int:
    return {"missing": 0, "low": 1, "medium": 2, "high": 3}.get(str(value), 0)


def _first_text(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
