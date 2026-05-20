import json
from pathlib import Path

from pretrip_models import (
    DtmCoverageSummary,
    DtmTileCandidate,
    PreTripSegmentCandidate,
    ProjectedBBox,
    RouteBBox,
)
from pretrip_terrain_summary import summarize_segment_terrain_metadata


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_chilai_fixture_segments_link_to_dtm_metadata_without_rasters():
    segments = [
        PreTripSegmentCandidate.model_validate(item)
        for item in json.loads((FIXTURE_ROOT / "candidates" / "segments.json").read_text())
    ]
    coverage = DtmCoverageSummary.model_validate(
        json.loads((FIXTURE_ROOT / "normalized" / "terrain" / "dtm_coverage_summary.json").read_text())
    )

    summary = summarize_segment_terrain_metadata(
        segment_candidates=segments,
        dtm_coverage_summary=coverage,
        summary_id="terrain_summary.chilai_nanhua_day1.test",
    )

    assert summary.summary_id == "terrain_summary.chilai_nanhua_day1.test"
    assert summary.route_artifact_id == coverage.route_artifact_id
    assert summary.segment_count == 10
    assert summary.candidate_tile_count == 10
    assert summary.unlinked_segment_ids == []
    assert [item.segment_candidate_id for item in summary.segment_metadata] == [
        segment.candidate_id for segment in segments
    ]
    assert summary.segment_metadata[0].progress_start_m == 0.0
    assert summary.segment_metadata[-1].progress_end_m == round(sum(segment.distance_m for segment in segments), 3)
    assert all(item.candidate_tiles for item in summary.segment_metadata)
    assert all(
        tile.tile_ref.startswith(("南投縣:", "花蓮縣:"))
        for item in summary.segment_metadata
        for tile in item.candidate_tiles
    )


def test_chilai_segment_dtm_coverage_fixture_validates():
    payload = json.loads((FIXTURE_ROOT / "normalized" / "terrain" / "segment_dtm_coverage.json").read_text())
    coverage = DtmCoverageSummary.model_validate(
        json.loads((FIXTURE_ROOT / "normalized" / "terrain" / "dtm_coverage_summary.json").read_text())
    )

    assert payload["summary_id"] == "terrain_summary.chilai_nanhua_day1.20m"
    assert payload["dtm_coverage_summary_id"] == coverage.summary_id
    assert payload["segment_count"] == 10
    assert payload["candidate_tile_count"] == 10
    assert payload["unlinked_segment_ids"] == []
    assert "header_uri" not in json.dumps(payload)
    assert "grid_uri" not in json.dumps(payload)


def test_synthetic_bbox_progress_links_segments_to_expected_tiles():
    coverage = DtmCoverageSummary(
        summary_id="dtm.synthetic",
        route_artifact_id="artifact.gpx.synthetic",
        route_bbox_wgs84=RouteBBox(min_lat=0.0, min_lon=0.0, max_lat=1.0, max_lon=1.0),
        route_bbox_twd97=ProjectedBBox(crs="fixture", min_x=0.0, min_y=0.0, max_x=100.0, max_y=100.0),
        candidate_tiles=[
            _tile("west", "A", 0.0, 0.0, 35.0, 35.0),
            _tile("east", "B", 55.0, 55.0, 100.0, 100.0),
            _tile("outside", "C", 150.0, 150.0, 200.0, 200.0),
        ],
        scanned_header_count=3,
        missing_grid_count=0,
    )
    segments = [
        _segment("seg.001", "cp.start", "cp.001", 40.0),
        _segment("seg.002", "cp.001", "cp.finish", 60.0),
    ]

    summary = summarize_segment_terrain_metadata(segment_candidates=segments, dtm_coverage_summary=coverage)

    assert summary.candidate_tile_count == 3
    assert summary.unlinked_segment_ids == []
    assert [tile.tile_ref for tile in summary.segment_metadata[0].candidate_tiles] == ["A:west"]
    assert [tile.tile_ref for tile in summary.segment_metadata[1].candidate_tiles] == ["B:east"]


def test_empty_tile_summary_keeps_segments_unlinked():
    coverage = DtmCoverageSummary(
        summary_id="dtm.empty",
        route_artifact_id="artifact.gpx.synthetic",
        route_bbox_wgs84=RouteBBox(min_lat=0.0, min_lon=0.0, max_lat=1.0, max_lon=1.0),
        route_bbox_twd97=ProjectedBBox(crs="fixture", min_x=0.0, min_y=0.0, max_x=100.0, max_y=100.0),
        candidate_tiles=[],
        scanned_header_count=0,
        missing_grid_count=0,
    )

    summary = summarize_segment_terrain_metadata(
        segment_candidates=[_segment("seg.001", "cp.start", "cp.finish", 100.0)],
        dtm_coverage_summary=coverage,
    )

    assert summary.unlinked_segment_ids == ["seg.001"]
    assert summary.segment_metadata[0].candidate_tiles == []


def _segment(
    candidate_id: str,
    from_candidate_id: str,
    to_candidate_id: str,
    distance_m: float,
) -> PreTripSegmentCandidate:
    return PreTripSegmentCandidate(
        candidate_id=candidate_id,
        label=candidate_id,
        from_candidate_id=from_candidate_id,
        to_candidate_id=to_candidate_id,
        distance_m=distance_m,
    )


def _tile(
    tile_id: str,
    county: str,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> DtmTileCandidate:
    return DtmTileCandidate(
        tile_id=tile_id,
        county=county,
        header_uri=f"/fixture/{tile_id}dem.hdr",
        grid_uri=None,
        horizontal_datum="TWD97",
        vertical_datum="TWVD2001",
        resolution_x_m=20.0,
        resolution_y_m=20.0,
        rows=1,
        cols=1,
        origin_x=min_x,
        origin_y=min_y,
        bbox_twd97=ProjectedBBox(crs="fixture", min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y),
        intersects_route_bbox=True,
    )
