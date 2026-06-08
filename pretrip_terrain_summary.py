from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pretrip_models import (
    DtmCoverageSummary,
    DtmTileCandidate,
    PreTripSegmentCandidate,
    ProjectedBBox,
)


class SegmentDtmTileMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tile_ref: str
    tile_id: str
    county: str
    progress_start_m: float = Field(ge=0.0)
    progress_end_m: float = Field(ge=0.0)
    match_reason: str


class SegmentTerrainMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_candidate_id: str
    from_candidate_id: str
    to_candidate_id: str
    route_point_start_index: int | None = None
    route_point_end_index: int | None = None
    progress_start_m: float = Field(ge=0.0)
    progress_end_m: float = Field(ge=0.0)
    candidate_tiles: list[SegmentDtmTileMetadata] = Field(default_factory=list)
    notes: str = ""


class PreTripTerrainSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_id: str
    route_artifact_id: str
    dtm_coverage_summary_id: str
    route_bbox_twd97: ProjectedBBox
    segment_count: int = Field(ge=0)
    candidate_tile_count: int = Field(ge=0)
    segment_metadata: list[SegmentTerrainMetadata] = Field(default_factory=list)
    unlinked_segment_ids: list[str] = Field(default_factory=list)
    notes: str = ""


def summarize_segment_terrain_metadata(
    *,
    segment_candidates: list[PreTripSegmentCandidate],
    dtm_coverage_summary: DtmCoverageSummary,
    summary_id: str | None = None,
) -> PreTripTerrainSummary:
    total_distance_m = sum(segment.distance_m for segment in segment_candidates)
    tile_progress = _tile_progress_ranges(dtm_coverage_summary, total_distance_m)
    segment_ranges = _segment_progress_ranges(segment_candidates)
    segment_metadata: list[SegmentTerrainMetadata] = []

    for segment, progress_start_m, progress_end_m in segment_ranges:
        matching_tiles = [
            tile
            for tile in tile_progress
            if _ranges_overlap(progress_start_m, progress_end_m, tile.progress_start_m, tile.progress_end_m)
        ]
        match_reason = "bbox_progress_overlap"
        if not matching_tiles and tile_progress:
            segment_midpoint_m = (progress_start_m + progress_end_m) / 2.0
            nearest_distance_m = min(abs(tile.progress_midpoint_m - segment_midpoint_m) for tile in tile_progress)
            matching_tiles = [
                tile for tile in tile_progress if abs(tile.progress_midpoint_m - segment_midpoint_m) == nearest_distance_m
            ]
            match_reason = "nearest_bbox_progress"

        segment_metadata.append(
            SegmentTerrainMetadata(
                segment_candidate_id=segment.candidate_id,
                from_candidate_id=segment.from_candidate_id,
                to_candidate_id=segment.to_candidate_id,
                route_point_start_index=segment.route_point_start_index,
                route_point_end_index=segment.route_point_end_index,
                progress_start_m=round(progress_start_m, 3),
                progress_end_m=round(progress_end_m, 3),
                candidate_tiles=[
                    SegmentDtmTileMetadata(
                        tile_ref=tile.tile_ref,
                        tile_id=tile.tile.tile_id,
                        county=tile.tile.county,
                        progress_start_m=round(tile.progress_start_m, 3),
                        progress_end_m=round(tile.progress_end_m, 3),
                        match_reason=match_reason,
                    )
                    for tile in sorted(matching_tiles, key=lambda item: item.tile_ref)
                ],
                notes=(
                    "Segment progress is approximated from candidate distances; "
                    "tile progress is approximated from DTM bbox overlap with route bbox."
                ),
            )
        )

    return PreTripTerrainSummary(
        summary_id=summary_id or f"terrain_summary.{dtm_coverage_summary.summary_id}",
        route_artifact_id=dtm_coverage_summary.route_artifact_id,
        dtm_coverage_summary_id=dtm_coverage_summary.summary_id,
        route_bbox_twd97=dtm_coverage_summary.route_bbox_twd97,
        segment_count=len(segment_candidates),
        candidate_tile_count=len(dtm_coverage_summary.candidate_tiles),
        segment_metadata=segment_metadata,
        unlinked_segment_ids=[
            item.segment_candidate_id for item in segment_metadata if not item.candidate_tiles
        ],
        notes="Metadata-only Phase 4 terrain summary; does not read or copy DTM grid rasters.",
    )


class _TileProgressRange(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    tile_ref: str
    tile: DtmTileCandidate
    progress_start_m: float
    progress_end_m: float

    @property
    def progress_midpoint_m(self) -> float:
        return (self.progress_start_m + self.progress_end_m) / 2.0


def _segment_progress_ranges(
    segment_candidates: list[PreTripSegmentCandidate],
) -> list[tuple[PreTripSegmentCandidate, float, float]]:
    progress_start_m = 0.0
    ranges: list[tuple[PreTripSegmentCandidate, float, float]] = []
    for segment in segment_candidates:
        progress_end_m = progress_start_m + segment.distance_m
        ranges.append((segment, progress_start_m, progress_end_m))
        progress_start_m = progress_end_m
    return ranges


def _tile_progress_ranges(
    dtm_coverage_summary: DtmCoverageSummary,
    total_distance_m: float,
) -> list[_TileProgressRange]:
    ranges: list[_TileProgressRange] = []
    route_bbox = dtm_coverage_summary.route_bbox_twd97
    for tile in dtm_coverage_summary.candidate_tiles:
        if not tile.intersects_route_bbox:
            continue
        intersection = _bbox_intersection(route_bbox, tile.bbox_twd97)
        if intersection is None:
            continue
        fraction_start, fraction_end = _bbox_fraction_range(route_bbox, intersection)
        ranges.append(
            _TileProgressRange(
                tile_ref=f"{tile.county}:{tile.tile_id}",
                tile=tile,
                progress_start_m=fraction_start * total_distance_m,
                progress_end_m=fraction_end * total_distance_m,
            )
        )
    return sorted(ranges, key=lambda item: item.tile_ref)


def _bbox_intersection(a: ProjectedBBox, b: ProjectedBBox) -> ProjectedBBox | None:
    min_x = max(a.min_x, b.min_x)
    min_y = max(a.min_y, b.min_y)
    max_x = min(a.max_x, b.max_x)
    max_y = min(a.max_y, b.max_y)
    if min_x > max_x or min_y > max_y:
        return None
    return ProjectedBBox(crs=a.crs, min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _bbox_fraction_range(route_bbox: ProjectedBBox, bbox: ProjectedBBox) -> tuple[float, float]:
    width = route_bbox.max_x - route_bbox.min_x
    height = route_bbox.max_y - route_bbox.min_y
    fractions = [
        _progress_fraction(route_bbox, width, height, x, y)
        for x in (bbox.min_x, bbox.max_x)
        for y in (bbox.min_y, bbox.max_y)
    ]
    return min(fractions), max(fractions)


def _progress_fraction(route_bbox: ProjectedBBox, width: float, height: float, x: float, y: float) -> float:
    x_fraction = _axis_fraction(x, route_bbox.min_x, width)
    y_fraction = _axis_fraction(y, route_bbox.min_y, height)
    return (x_fraction + y_fraction) / 2.0


def _axis_fraction(value: float, origin: float, span: float) -> float:
    if span <= 0.0:
        return 0.0
    return min(1.0, max(0.0, (value - origin) / span))


def _ranges_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
    return start_a <= end_b and start_b <= end_a
