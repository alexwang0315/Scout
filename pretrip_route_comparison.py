from __future__ import annotations

from pathlib import Path
from typing import Any

from pretrip_models import PreTripRouteSummary, RouteBBox
from pretrip_source_ingest import sha256_file, summarize_gpx


DEFAULT_PRIMARY_GPX = Path("/Users/alexwang0315/downloads/奇萊南華-能高越嶺步道Day1.gpx")
DEFAULT_SIMILAR_GPX = Path("/Users/alexwang0315/downloads/6966d6fa4d9d9652b2da064c7345fb22_p.gpx")


def build_chilai_route_comparison(
    *,
    primary_gpx_path: Path = DEFAULT_PRIMARY_GPX,
    similar_gpx_path: Path = DEFAULT_SIMILAR_GPX,
) -> dict[str, Any]:
    return build_route_comparison(
        comparison_id="route_comparison.chilai_nanhua_day1.similar_gpx.v0",
        primary_gpx_path=primary_gpx_path,
        comparison_gpx_path=similar_gpx_path,
        primary_artifact_id="artifact.gpx.chilai_nanhua_day1",
        comparison_artifact_id="artifact.gpx.chilai_nanhua_day1.similar_reference",
    )


def build_route_comparison(
    *,
    comparison_id: str,
    primary_gpx_path: Path,
    comparison_gpx_path: Path,
    primary_artifact_id: str,
    comparison_artifact_id: str,
) -> dict[str, Any]:
    primary_summary = summarize_gpx(primary_gpx_path, primary_artifact_id)
    comparison_summary = summarize_gpx(comparison_gpx_path, comparison_artifact_id)
    bbox = _bbox_comparison(primary_summary.bbox_wgs84, comparison_summary.bbox_wgs84)

    return {
        "comparison_id": comparison_id,
        "classification": "comparison_only",
        "source_use_treatment": {
            "primary_user_provided_source": True,
            "external_reference_comparison_only": True,
            "redistributable_fixture_allowed": False,
            "derived_summary_only": True,
            "raw_source_versioned": False,
            "authoritative_for_mission": False,
            "compiled_into_mission_graph": False,
            "treatment_levels": [
                "primary_user_provided_source",
                "external_reference_comparison_only",
                "derived_summary_only",
                "non_authoritative_non_compiled_reference",
            ],
        },
        "primary_route": _route_entry(primary_gpx_path, primary_summary),
        "comparison_route": _route_entry(comparison_gpx_path, comparison_summary),
        "bbox_comparison": bbox,
        "distance_delta_m": round(
            comparison_summary.distance_m - primary_summary.distance_m,
            2,
        ),
        "point_count_delta": comparison_summary.point_count - primary_summary.point_count,
        "notes": [
            "Metadata-only comparison output; raw GPX track data is not copied into repo fixtures.",
            "External reference GPX is represented as derived summary, hash, bbox, distance, and point deltas only.",
            "Similar GPX is comparison-only evidence and is not authoritative for the Chilai-Nanhua plan.",
            "Comparison route is not compiled into MissionGraph and does not alter candidate checkpoints, segments, or retreat routes.",
        ],
    }


def _route_entry(path: Path, summary: PreTripRouteSummary) -> dict[str, Any]:
    source = path.expanduser().resolve()
    return {
        "artifact_id": summary.artifact_id,
        "route_name": summary.route_name,
        "source_uri": source.as_posix(),
        "sha256": sha256_file(source),
        "size_bytes": source.stat().st_size,
        "point_count": summary.point_count,
        "distance_m": summary.distance_m,
        "bbox_wgs84": summary.bbox_wgs84.model_dump(mode="json"),
        "elevation_range_m": {
            "min": summary.elevation_min_m,
            "max": summary.elevation_max_m,
        },
        "timestamp_range": {
            "started_at": summary.started_at,
            "ended_at": summary.ended_at,
        },
    }


def _bbox_comparison(primary: RouteBBox, comparison: RouteBBox) -> dict[str, Any]:
    intersection = _bbox_intersection(primary, comparison)
    primary_area = _bbox_area(primary)
    comparison_area = _bbox_area(comparison)
    intersection_area = _bbox_area(intersection) if intersection is not None else 0.0
    return {
        "overlaps": intersection is not None,
        "intersection_wgs84": intersection.model_dump(mode="json") if intersection else None,
        "intersection_area_degrees2": round(intersection_area, 10),
        "primary_overlap_ratio": _ratio(intersection_area, primary_area),
        "comparison_overlap_ratio": _ratio(intersection_area, comparison_area),
    }


def _bbox_intersection(a: RouteBBox, b: RouteBBox) -> RouteBBox | None:
    min_lat = max(a.min_lat, b.min_lat)
    min_lon = max(a.min_lon, b.min_lon)
    max_lat = min(a.max_lat, b.max_lat)
    max_lon = min(a.max_lon, b.max_lon)
    if min_lat > max_lat or min_lon > max_lon:
        return None
    return RouteBBox(
        min_lat=round(min_lat, 7),
        min_lon=round(min_lon, 7),
        max_lat=round(max_lat, 7),
        max_lon=round(max_lon, 7),
    )


def _bbox_area(bbox: RouteBBox) -> float:
    return max(0.0, bbox.max_lat - bbox.min_lat) * max(0.0, bbox.max_lon - bbox.min_lon)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return round(numerator / denominator, 6)
