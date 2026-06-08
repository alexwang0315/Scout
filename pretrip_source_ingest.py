from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from geo_utils import haversine_m
from pretrip_models import (
    DtmCoverageSummary,
    DtmTileCandidate,
    PreTripArtifactKind,
    PreTripPackage,
    PreTripPlanningReference,
    PreTripProvenance,
    PreTripRetreatRouteCandidate,
    PreTripRouteGuideTimingCandidate,
    PreTripRouteSummary,
    PreTripSourceArtifact,
    ProjectedBBox,
    RouteBBox,
)
from pretrip_candidate_generation import generate_pretrip_candidates_from_gpx
from route_matching import load_gpx_route


TWD97_CRS = "TWD97 / TM2 zone 121 (EPSG:3826-compatible)"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_source_artifact(
    *,
    artifact_id: str,
    path: Path,
    kind: PreTripArtifactKind,
    media_type: str | None,
    method: str,
    metadata: dict | None = None,
) -> PreTripSourceArtifact:
    source = path.expanduser().resolve()
    stat = source.stat()
    return PreTripSourceArtifact(
        artifact_id=artifact_id,
        kind=kind,
        uri=source.as_posix(),
        media_type=media_type,
        sha256=sha256_file(source),
        size_bytes=stat.st_size,
        provenance=PreTripProvenance(
            source_ref=artifact_id,
            source_kind=kind,
            uri=source.as_posix(),
            method=method,
        ),
        metadata=metadata or {},
    )


def summarize_gpx(gpx_path: Path, artifact_id: str) -> PreTripRouteSummary:
    route = load_gpx_route(gpx_path)
    elevations = [point.elevation_m for point in route.points if point.elevation_m is not None]
    return PreTripRouteSummary(
        artifact_id=artifact_id,
        route_name=_gpx_route_name(gpx_path) or Path(gpx_path).stem,
        point_count=len(route.points),
        distance_m=round(route.points[-1].progress_m, 2),
        bbox_wgs84=RouteBBox(
            min_lat=min(point.lat for point in route.points),
            min_lon=min(point.lon for point in route.points),
            max_lat=max(point.lat for point in route.points),
            max_lon=max(point.lon for point in route.points),
        ),
        elevation_min_m=round(min(elevations), 2) if elevations else None,
        elevation_max_m=round(max(elevations), 2) if elevations else None,
        started_at=route.points[0].timestamp,
        ended_at=route.points[-1].timestamp,
    )


def _gpx_route_name(gpx_path: Path) -> str | None:
    root = ET.parse(gpx_path).getroot()
    ns = _namespace(root)
    return root.findtext("g:metadata/g:name", namespaces=ns) or root.findtext("g:trk/g:name", namespaces=ns)


def _namespace(root: ET.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": "http://www.topografix.com/GPX/1/1"}


def scan_dtm_coverage(
    *,
    route_summary: PreTripRouteSummary,
    source_dirs: list[Path],
    summary_id: str,
) -> DtmCoverageSummary:
    route_bbox_twd97 = project_route_bbox_to_twd97(route_summary.bbox_wgs84)
    candidates: list[DtmTileCandidate] = []
    scanned_header_count = 0
    missing_grid_count = 0

    for source_dir in source_dirs:
        for header_path in sorted(Path(source_dir).glob("*dem.hdr")):
            scanned_header_count += 1
            tile = parse_dtm_header(header_path)
            if tile.grid_uri is None:
                missing_grid_count += 1
            if _bbox_intersects(route_bbox_twd97, tile.bbox_twd97):
                candidates.append(tile)

    candidates.sort(key=lambda tile: (tile.county, tile.tile_id))
    return DtmCoverageSummary(
        summary_id=summary_id,
        route_artifact_id=route_summary.artifact_id,
        source_dirs=[Path(path).resolve().as_posix() for path in source_dirs],
        route_bbox_wgs84=route_summary.bbox_wgs84,
        route_bbox_twd97=route_bbox_twd97,
        candidate_tiles=candidates,
        scanned_header_count=scanned_header_count,
        missing_grid_count=missing_grid_count,
        notes="DTM tiles are referenced by metadata only; source rasters are not copied into repo fixtures.",
    )


def parse_dtm_header(header_path: Path) -> DtmTileCandidate:
    lines = header_path.read_text(encoding="big5", errors="replace").splitlines()
    if len(lines) < 12:
        raise ValueError(f"DTM header is too short: {header_path}")

    tile_id = lines[1].strip()
    horizontal_datum = lines[2].strip()
    vertical_datum = lines[3].strip()
    resolution_x_m = float(lines[5])
    resolution_y_m = float(lines[6])
    rows = int(lines[8])
    cols = int(lines[9])
    origin_x = float(lines[10])
    origin_y = float(lines[11])
    max_x = origin_x + (cols * resolution_x_m)
    max_y = origin_y + (rows * resolution_y_m)
    grid_path = header_path.with_suffix(".grd")
    county = _county_from_source_dir(header_path.parent)

    return DtmTileCandidate(
        tile_id=tile_id,
        county=county,
        header_uri=header_path.resolve().as_posix(),
        grid_uri=grid_path.resolve().as_posix() if grid_path.exists() else None,
        horizontal_datum=horizontal_datum,
        vertical_datum=vertical_datum,
        resolution_x_m=resolution_x_m,
        resolution_y_m=resolution_y_m,
        rows=rows,
        cols=cols,
        origin_x=origin_x,
        origin_y=origin_y,
        bbox_twd97=ProjectedBBox(
            crs=TWD97_CRS,
            min_x=origin_x,
            min_y=origin_y,
            max_x=max_x,
            max_y=max_y,
        ),
        coverage_note="intersects GPX bounding box in TWD97 projected coordinates",
    )


def _county_from_source_dir(path: Path) -> str:
    match = re.search(r"分幅_(.+?)20MDEM", path.name)
    return match.group(1) if match else path.name


def project_route_bbox_to_twd97(bbox: RouteBBox) -> ProjectedBBox:
    corners = [
        wgs84_to_twd97(bbox.min_lat, bbox.min_lon),
        wgs84_to_twd97(bbox.min_lat, bbox.max_lon),
        wgs84_to_twd97(bbox.max_lat, bbox.min_lon),
        wgs84_to_twd97(bbox.max_lat, bbox.max_lon),
    ]
    xs = [corner[0] for corner in corners]
    ys = [corner[1] for corner in corners]
    return ProjectedBBox(
        crs=TWD97_CRS,
        min_x=round(min(xs), 3),
        min_y=round(min(ys), 3),
        max_x=round(max(xs), 3),
        max_y=round(max(ys), 3),
    )


def wgs84_to_twd97(lat: float, lon: float) -> tuple[float, float]:
    a = 6378137.0
    b = 6356752.314245
    lon0 = math.radians(121.0)
    k0 = 0.9999
    dx = 250000.0

    e = math.sqrt(1 - (b * b) / (a * a))
    e2 = e * e / (1 - e * e)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)

    n = a / math.sqrt(1 - (e * math.sin(lat_rad)) ** 2)
    t = math.tan(lat_rad) ** 2
    c = e2 * math.cos(lat_rad) ** 2
    a_lon = math.cos(lat_rad) * (lon_rad - lon0)
    m = a * (
        (1.0 - e**2 / 4.0 - 3.0 * e**4 / 64.0 - 5.0 * e**6 / 256.0) * lat_rad
        - (3.0 * e**2 / 8.0 + 3.0 * e**4 / 32.0 + 45.0 * e**6 / 1024.0) * math.sin(2.0 * lat_rad)
        + (15.0 * e**4 / 256.0 + 45.0 * e**6 / 1024.0) * math.sin(4.0 * lat_rad)
        - (35.0 * e**6 / 3072.0) * math.sin(6.0 * lat_rad)
    )

    x = dx + k0 * n * (
        a_lon
        + (1.0 - t + c) * a_lon**3 / 6.0
        + (5.0 - 18.0 * t + t**2 + 72.0 * c - 58.0 * e2) * a_lon**5 / 120.0
    )
    y = k0 * (
        m
        + n
        * math.tan(lat_rad)
        * (
            a_lon**2 / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c**2) * a_lon**4 / 24.0
            + (61.0 - 58.0 * t + t**2 + 600.0 * c - 330.0 * e2) * a_lon**6 / 720.0
        )
    )
    return x, y


def _bbox_intersects(a: ProjectedBBox, b: ProjectedBBox) -> bool:
    return not (a.max_x < b.min_x or a.min_x > b.max_x or a.max_y < b.min_y or a.min_y > b.max_y)


def build_pretrip_package(
    *,
    package_id: str,
    project_id: str,
    version: str,
    gpx_path: Path,
    image_path: Path,
    dtm_dirs: list[Path],
    checkpoint_spacing_m: float = 1_500.0,
    planning_references: list[PreTripPlanningReference] | None = None,
    retreat_route_candidates: list[PreTripRetreatRouteCandidate] | None = None,
    route_guide_timing_candidates: list[PreTripRouteGuideTimingCandidate] | None = None,
) -> PreTripPackage:
    gpx_artifact = ingest_source_artifact(
        artifact_id="artifact.gpx.chilai_nanhua_day1",
        path=gpx_path,
        kind=PreTripArtifactKind.GPX,
        media_type="application/gpx+xml",
        method="pretrip-source-ingest",
    )
    image_artifact = ingest_source_artifact(
        artifact_id="artifact.photo.g11_hiking",
        path=image_path,
        kind=PreTripArtifactKind.PHOTO,
        media_type="image/jpeg",
        method="pretrip-source-ingest",
    )
    route_summary = summarize_gpx(gpx_path, gpx_artifact.artifact_id)
    coverage_summary = scan_dtm_coverage(
        route_summary=route_summary,
        source_dirs=dtm_dirs,
        summary_id="dtm_coverage.chilai_nanhua_day1.20m",
    )
    candidate_result = generate_pretrip_candidates_from_gpx(
        gpx_path,
        checkpoint_spacing_m=checkpoint_spacing_m,
        source_ref=gpx_artifact.artifact_id,
    )
    return PreTripPackage(
        package_id=package_id,
        project_id=project_id,
        version=version,
        route_summary=route_summary,
        source_artifacts=[gpx_artifact, image_artifact],
        planning_references=planning_references or [],
        dtm_coverage_summary=coverage_summary,
        checkpoint_candidates=candidate_result.checkpoint_candidates,
        segment_candidates=candidate_result.segment_candidates,
        retreat_route_candidates=retreat_route_candidates or [],
        route_guide_timing_candidates=route_guide_timing_candidates or [],
        readiness_notes=[
            "multiday traverse planning requires reviewed alternate or retreat route before MissionGraph compile",
            "source ingest and DTM coverage are metadata-only in this slice",
            "when pace multiplier basis is unknown, readiness ETA should default to total elapsed time including normal rest",
        ],
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
